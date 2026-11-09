"""Adapters: API contracts against recorded response shapes, state, and configuration."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
import responses

from autolister_core.accounts import load_accounts
from autolister_core.instructions import Action, Instruction, unseal
from autolister_core.protocol import LOOKSRARE_API
from autolister_engine.adapters.floor import FloorOracle, FloorReading, alchemy, nftbank
from autolister_engine.adapters.looksrare import LooksRareClient
from autolister_engine.adapters.pubsub import PubSubPublisher
from autolister_engine.adapters.secrets import SecretManagerStore
from autolister_engine.adapters.state import JsonStateStore
from autolister_engine.config import Strategy
from autolister_engine.domain.models import Floor, ListingState

from tests.fakes import COLLECTION, NOW, OTHER, REPO, book, eth


def order(i: int, price: int) -> dict:
    return {
        "hash": f"0x{i:064x}",
        "collectionAddress": COLLECTION,
        "tokenId": str(i),
        "isOrderAsk": True,
        "signer": OTHER,
        "price": str(price),
        "nonce": str(i),
        "endTime": 2_000_000_000,
        "status": "VALID",
    }


@responses.activate
def test_listings_follow_the_pagination_cursor():
    page1 = [order(i, eth("1") + i) for i in range(150)]
    page2 = [order(150 + i, eth("2") + i) for i in range(20)]
    responses.add(responses.GET, f"{LOOKSRARE_API}/orders", json={"success": True, "data": page1})
    responses.add(responses.GET, f"{LOOKSRARE_API}/orders", json={"success": True, "data": page2})

    listings = LooksRareClient().listings(COLLECTION, 200, eth("0.1"))

    assert len(listings) == 170
    first, second = (call.request.url for call in responses.calls)
    assert "pagination%5Bfirst%5D=150" in first and "cursor" not in first
    assert (
        "pagination%5Bfirst%5D=50" in second
        and f"pagination%5Bcursor%5D={page1[-1]['hash']}" in second
    )


@responses.activate
def test_sales_and_rewards_endpoints():
    responses.add(
        responses.GET,
        f"{LOOKSRARE_API}/events",
        json={"data": [{"createdAt": "2022-10-17T00:00:00.000Z"}]},
    )
    responses.add(
        responses.GET,
        f"{LOOKSRARE_API}/collections/listing-rewards",
        json={
            "data": [
                {"collection": {"address": "0xaaa"}},
                {"collection": {"address": COLLECTION.lower()}},
            ]
        },
    )
    client = LooksRareClient()
    assert client.last_sale_time(COLLECTION) == 1_665_964_800.0
    assert client.earns_listing_rewards(COLLECTION, top_n=5)


@responses.activate
def test_floor_providers_and_the_oracle():
    responses.add(
        responses.GET,
        "https://eth-mainnet.g.alchemy.com/nft/v2/key/getFloorPrice",
        json={"openSea": {"floorPrice": 1.52, "retrievedAt": "2022-10-17T00:00:00.000Z"}},
    )
    responses.add(
        responses.GET,
        f"https://api.nftbank.ai/estimates-v2/floor_price/{COLLECTION}",
        json={
            "data": [
                {
                    "estimated_at": "Mon, 17 Oct 2022 02:00:00 GMT",
                    "floor_price": [
                        {"marketplace": "looksrare", "floor_price": 1.6},
                        {"marketplace": "opensea", "floor_price": 1.49},
                    ],
                }
            ]
        },
    )
    assert alchemy("key")(COLLECTION) == FloorReading(eth("1.52"), 1_665_964_800.0)
    assert nftbank("key")(COLLECTION) == FloorReading(eth("1.49"), 1_665_972_000.0)

    def broken(_: str) -> FloorReading:
        raise ConnectionError("down")

    oracle = FloorOracle([alchemy("key"), broken, nftbank("key")])
    assert oracle.current(COLLECTION, book([eth("1.6")])) == Floor(
        eth("1.6"), eth("1.49")
    )  # freshest wins


def test_json_state_round_trips(tmp_path):
    store = JsonStateStore(tmp_path)
    assert store.load_floor() is None
    store.save_floor(Floor(eth("1.0"), eth("0.99")))
    store.save("investor-1", ListingState(eth("1.07"), 123))
    reopened = JsonStateStore(tmp_path)
    assert reopened.load_floor() == Floor(eth("1.0"), eth("0.99"))
    assert reopened.load("investor-1") == ListingState(eth("1.07"), 123)


def test_committed_configuration_is_valid():
    assert Strategy.from_yaml(REPO / "config" / "strategy.yaml") == Strategy(
        collection_address=COLLECTION
    )
    accounts = load_accounts(REPO / "config" / "accounts.yaml")
    assert [a.id for a in accounts] == ["investor-1", "investor-2"]


@pytest.mark.parametrize(
    "override",
    [
        {"emergency_stop_rank": 30},
        {"target_premium_pct": "12"},
        {"listings_to_scan": 20},
        {"sharp_drop_ratio": "1"},
        {"unknown_setting": 1},
    ],
)
def test_inconsistent_strategies_are_rejected(override):
    with pytest.raises(ValueError):
        Strategy.parse_obj({"collection_address": COLLECTION, **override})


# ---------------------------------------------------------------- Pub/Sub and Secret Manager


class FakePublisherClient:
    def __init__(self) -> None:
        self.published: list[tuple[str, bytes, dict[str, str]]] = []

    def topic_path(self, project: str, topic: str) -> str:
        return f"projects/{project}/topics/{topic}"

    def publish(self, topic: str, data: bytes, **attributes: str) -> SimpleNamespace:
        self.published.append((topic, data, attributes))
        return SimpleNamespace(result=lambda timeout: "message-id")


def test_publishes_sealed_instructions_ordered_by_account():
    client = FakePublisherClient()
    instruction = Instruction(
        action=Action.LIST,
        account_id="investor-1",
        issued_at=NOW,
        price_wei=eth("1.3"),
        end_time=int(NOW) + 3 * 86_400,
    )
    PubSubPublisher("proj", "autolister-instructions", b"hmac-key", client=client).publish(
        instruction
    )

    [(topic, data, attributes)] = client.published
    assert topic == "projects/proj/topics/autolister-instructions"
    assert attributes == {"ordering_key": "investor-1", "action": "list"}
    assert unseal(data, b"hmac-key", now=NOW) == instruction  # exactly what the signer verifies


def test_reads_the_latest_version_of_a_secret():
    requests = []

    def access_secret_version(request):
        requests.append(request)
        return SimpleNamespace(payload=SimpleNamespace(data=b"s3cret\n"))  # pasted with a newline

    client = SimpleNamespace(access_secret_version=access_secret_version)
    assert SecretManagerStore("proj", client=client).get("alchemy-api-key") == "s3cret"
    assert requests == [{"name": "projects/proj/secrets/alchemy-api-key/versions/latest"}]
