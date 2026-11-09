# Runbook

What to do when an alert fires, and how to carry out routine operations. Every
alert links to its section here.

Commands assume you are at the repository root, authenticated with `gcloud` as
an operator, and that `infra/terraform/terraform.tfvars` holds the settings
currently deployed, including `image_tag`. Change one setting at a time.

```bash
export PROJECT=<project id> ZONE=europe-north1-a
```

## Where to look

Every log line is a JSON object with an `event` field;
[docs/architecture.md](architecture.md#log-events) lists them all. In Logs
Explorer:

| To see | Query |
|---|---|
| Everything, newest first | `resource.type="gce_instance" jsonPayload.event:*` |
| One account | `jsonPayload.account="investor-1"` |
| Problems only | `severity>=WARNING jsonPayload.event:*` |
| The engine's decisions | `jsonPayload.event="decision"` |
| What the signer did | `jsonPayload.event=("cancelled" OR "listed" OR "emergency_stop" OR "rejected")` |

## Stop things

From least to most drastic:

| To | Do | Takes |
|---|---|---|
| Stop new instructions | `terraform -chdir=infra/terraform apply -var trading_enabled=false` | A few minutes |
| Stop all signing | `terraform -chdir=infra/terraform apply -var signing_enabled=false`, or, faster, `gcloud compute instance-groups managed resize autolister-signer --size=0 --zone=$ZONE`, which lasts until the next apply | Seconds to minutes |
| Pull every listing now | [Cancel everything](#cancel-everything) | A few minutes, one transaction per wallet |

Stopping the engine also stops it protecting the listings that are live. If the
market is moving, cancel everything as well.

### Cancel everything

The break-glass command publishes a cancellation for each account. The signer
carries them out like any other instruction, so it must be running.

1. Stop new instructions first (above), or the engine's next cycle may list
   again.
2. From a checkout of the deployed commit:

   ```bash
   make install
   gcloud auth application-default login
   AUTOLISTER_GCP_PROJECT=$PROJECT .venv/bin/autolister-engine cancel-all --all
   ```

   Use `--account investor-1` (repeatable) instead of `--all` to cancel only
   some accounts.
3. Watch for one `cancelled` event per account.

## Alerts

### Emergency stop

**Meaning.** A listing was refused because its price was below the emergency
floor, the 21st cheapest ask. From the engine, the strategy proposed a price
that is too low, usually in a thin or fast-moving book, and nothing was
published. From the signer, it refused an instruction the engine thought was
safe: either the market moved between their two reads, or the engine is
misbehaving.

**Do.** Compare the event's `price_wei` with `guard_wei`.

- One event in a fast market: nothing. The engine decides again next cycle.
- Repeated events, or a signer refusal far below the guard: stop new
  instructions and work out why the engine is proposing those prices. Treat it
  as a possible compromise of the engine
  ([threat model](threat-model.md), threat 2).

### Rejected instruction

**Meaning.** The signer received an instruction with a bad seal, one it could
not parse, one for an unknown account, or one with an expiry out of range. None
of these happen in normal operation.

**Do.** Read the event's `message`.

- **Bad MAC** just after rotating the HMAC key: expected until both services
  have restarted ([rotate a key](#rotate-a-key)).
- **Unknown account** just after changing `config/accounts.yaml`: the services
  are running different versions. Deploy both from the same commit.
- **Anything else**: assume someone is trying to instruct the signer. Stop all
  signing, check who can publish to the `autolister-instructions` topic, and
  rotate the HMAC key.

### Service error

**Meaning.** One of the services hit an unexpected exception. The log entry has
the stack trace.

**Do.** Find it with `severity>=ERROR jsonPayload.event="error"`.

- Timeouts and 5xx responses from an API or the RPC endpoint clear by
  themselves: reads are retried, instructions are redelivered, and the engine
  tries again every cycle.
- Anything persistent is a bug or a broken dependency: roll back
  ([deploy](#deploy-or-roll-back)), then fix forward.

### Engine silent

**Meaning.** The engine has not completed a cycle for 10 minutes. Its VM is
down, crash-looping, or stuck.

**Do.**

```bash
gcloud compute instance-groups managed list-instances autolister-engine --zone=$ZONE
```

Check the engine's latest logs for errors, then [restart it](#restart-a-service).
While the engine is down, nothing manages the live listings: if the market is
moving, [cancel everything](#cancel-everything).

### Signer backlog

**Meaning.** An instruction has waited more than 10 minutes. The signer is
stopped, disabled, crash-looping, or waiting on something slow, usually a
cancellation that has not been mined.

**Do.**

- If signing is disabled on purpose, this is expected. Queued instructions
  expire after an hour and the engine issues fresh ones once signing resumes.
- Otherwise check the signer's logs. If a cancellation is waiting for gas, see
  [dead-lettered instruction](#dead-lettered-instruction). If the signer is
  stuck, [restart it](#restart-a-service).

### Dead-lettered instruction

**Meaning.** An instruction failed five times and was moved to the
`autolister-instructions-dead-letter` subscription, where it is kept for a
week.

**Do.** Find the cause in the signer's `error` events for that account:

- **The RPC endpoint or the LooksRare API was down**: nothing to do once it is
  back. The engine re-issues whatever is still needed.
- **A cancellation was not mined in time**, because gas prices rose above the
  signer's fee cap: raise it, for example
  `terraform -chdir=infra/terraform apply -var max_fee_gwei=120`, and lower it
  again once gas prices fall.

To look at dead letters (this does not remove them):

```bash
gcloud pubsub subscriptions pull autolister-instructions-dead-letter --limit=10
```

Never republish a dead letter. By now it is stale, and the engine will already
have issued whatever is still needed.

### A wallet key may be exposed

**Meaning.** A wallet key was read by an identity other than the signer, or
there is any other reason to think a key has leaked.

**Do.** Whoever has the key no longer needs our signer, so stopping it does not
help. Speed matters:

1. **Move the assets.** With a wallet tool, outside this system, transfer the
   wallet's NFTs and funds to the investor's rescue wallet. Rescue wallets are
   prepared in advance, and their keys are kept offline.
2. **Pull the account.** Remove it from `config/accounts.yaml` and deploy, then
   disable the old key with
   `gcloud secrets versions disable <version> --secret=wallet-<id>`.
3. **Investigate.** The audit log records every read of the secret: who, from
   where, and when.
4. **Bring the account back** with a new wallet, as for a
   [new account](#add-an-account).

## Routine operations

### Deploy or roll back

CI pushes both images on every merge to `main`, tagged with the commit SHA.
Deploy from a checkout of that commit, because Terraform reads
`config/accounts.yaml` too:

```bash
git checkout <sha>
terraform -chdir=infra/terraform plan -var image_tag=<sha> -out=deploy.plan
terraform -chdir=infra/terraform apply deploy.plan
```

Each VM is replaced, the old one stopping before the new one starts. Watch for a
`start` event from each service, then the engine's `market` events. To roll
back, deploy the previous SHA the same way.

### Change the strategy

The strategy cannot be tested against the live market in CI, so a change runs
in *shadow mode* first: the engine decides, and logs its decisions, but
publishes nothing.

1. Change `config/strategy.yaml` in a pull request, and merge it once reviewed.
2. Deploy it with trading disabled: add `-var trading_enabled=false` to the
   deploy.
3. Read a few cycles of `decision` events and check they are what you expect.
4. Deploy again with trading enabled.

Nothing manages the live listings during step 3, so keep it short, and choose a
calm market for it.

### Add an account

1. The investor's wallet approves LooksRare's transfer manager for the
   collection. This is done once, by hand, with the wallet; the system never
   grants approvals.
2. Add the account to `config/accounts.yaml` in a pull request. Its id becomes
   part of a secret's name, so use lowercase letters, digits and hyphens.
3. Deploy the merged commit with trading disabled, which pauses every account
   for a few minutes. This creates the `wallet-<id>` secret, readable only by
   the signer.
4. Add the key, without leaving it in your shell history or on disk:

   ```bash
   gcloud secrets versions add wallet-<id> --data-file=-   # paste, then Ctrl-D
   ```

5. Deploy again with trading enabled, and watch for the account's first
   `decision` and `listed` events.

### Rotate a key

| Secret | How |
|---|---|
| `alchemy-api-key`, `nftbank-api-key`, `looksrare-api-key`, `eth-rpc-url` | Add a new version, [restart](#restart-a-service) the service that uses it, then disable the old version |
| `instruction-hmac-key` | Add a new version, then restart the signer and the engine together. Instructions sealed with the old key while they restart are rejected, and the engine re-issues them |
| `wallet-<id>` | A wallet key cannot be rotated in place: move the assets to a new wallet, as in [a wallet key may be exposed](#a-wallet-key-may-be-exposed) |

To add a version: `gcloud secrets versions add <name> --data-file=-`.

### Restart a service

```bash
GROUP=autolister-signer   # or autolister-engine
gcloud compute instance-groups managed recreate-instances $GROUP --zone=$ZONE \
  --instances="$(gcloud compute instance-groups managed list-instances $GROUP \
    --zone=$ZONE --format='value(instance.basename())')"
```

Recreating replaces the VM: the old one is deleted before the new one starts.

## First-time setup

Done once per project, by a project owner.

1. **State bucket.**

   ```bash
   gsutil mb -l europe-north1 gs://$PROJECT-terraform-state
   gsutil versioning set on gs://$PROJECT-terraform-state
   ```

2. **Settings.** Copy `infra/terraform/terraform.tfvars.example` to
   `terraform.tfvars` and fill it in, then initialise:

   ```bash
   terraform -chdir=infra/terraform init -backend-config="bucket=$PROJECT-terraform-state"
   ```

3. **Foundations: secrets, registry and CI identity.** There are no images yet,
   so create these first:

   ```bash
   terraform -chdir=infra/terraform apply -var image_tag=none \
     -target=google_secret_manager_secret.secrets \
     -target=google_artifact_registry_repository_iam_member.ci_pushes \
     -target=google_iam_workload_identity_pool_provider.github \
     -target=google_service_account_iam_member.ci_federation
   ```

4. **Secret values.** Add a version to each secret in
   `terraform -chdir=infra/terraform output secrets_to_populate`. The HMAC key
   is 32 random bytes:

   ```bash
   openssl rand -hex 32 | gcloud secrets versions add instruction-hmac-key --data-file=-
   ```

5. **CI.** Set the repository secrets `ARTIFACT_REGISTRY`,
   `ARTIFACT_REGISTRY_HOST`, `WORKLOAD_IDENTITY_PROVIDER` and
   `CI_SERVICE_ACCOUNT` from `terraform output`, then run CI on `main` to push
   the first images.
6. **Approvals.** Each wallet approves LooksRare's transfer manager for the
   collection, as in [add an account](#add-an-account).
7. **Everything else**, in shadow mode first:

   ```bash
   terraform -chdir=infra/terraform apply -var image_tag=<sha> -var trading_enabled=false
   ```

   Check the engine's decisions, then deploy again with trading enabled.
