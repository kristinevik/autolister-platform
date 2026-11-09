import pytest

from autolister_core.instructions import Action
from autolister_engine.__main__ import parse_args
from autolister_engine.breakglass import cancel_everything

from tests.fakes import NOW, FakePublisher

ACCOUNT_IDS = ("investor-1", "investor-2")


@pytest.fixture
def accounts(account):
    return (account, account.copy(update={"id": "investor-2"}))


def test_cancels_every_account_by_default(accounts, caplog):
    publisher = FakePublisher()
    assert cancel_everything(publisher, accounts, None, now=NOW) == list(ACCOUNT_IDS)
    assert [(i.action, i.account_id) for i in publisher.published] == [
        (Action.CANCEL_ALL, "investor-1"),
        (Action.CANCEL_ALL, "investor-2"),
    ]
    assert [r.event for r in caplog.records] == ["manual_cancel", "manual_cancel"]


def test_cancels_only_the_accounts_named(accounts):
    publisher = FakePublisher()
    cancel_everything(publisher, accounts, ["investor-2"], now=NOW)
    assert [i.account_id for i in publisher.published] == ["investor-2"]


def test_refuses_unknown_accounts_before_publishing_anything(accounts):
    publisher = FakePublisher()
    with pytest.raises(ValueError, match="investor-9"):
        cancel_everything(publisher, accounts, ["investor-1", "investor-9"], now=NOW)
    assert publisher.published == []


def test_command_line():
    assert parse_args([]).command is None  # runs the pricing loop
    assert parse_args(["cancel-all", "--all"]).all
    assert parse_args(["cancel-all", "--account", "a", "--account", "b"]).account == ["a", "b"]
    with pytest.raises(SystemExit):
        parse_args(["cancel-all"])  # must say which accounts
