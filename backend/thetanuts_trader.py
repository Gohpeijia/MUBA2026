# thetanuts_trader.py
#
# Wraps the Thetanuts CLI + a read-only Web3 connection so the rest of the
# stack (ai_agent.py, prompt_engine.py, future routes) can:
#   1. Know exactly how much real, spendable capital the wallet has
#      (get_wallet_balance) before the AI ever proposes a size.
#   2. Fetch live OptionBook orders in a predictable {ok, data, error} shape.
#   3. Fill an order and get back a structured result — and have EVERY
#      attempt (success, failure, or dry-run) written to a durable local
#      log, independent of whether Firestore is configured.
#
# Required env vars (.env):
#   WALLET_PRIVATE_KEY   - the trading wallet's private key (0x...)
#   BASE_RPC_URL          - optional, defaults to the public Base RPC

import subprocess
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from web3 import Web3
from eth_account import Account

# ── Base Mainnet constants ──────────────────────────────────────────────
BASE_MAINNET_CHAIN_ID = 8453
DEFAULT_RPC_URL = "https://mainnet.base.org"

# Native USDC on Base.
USDC_BASE_ADDRESS = Web3.to_checksum_address("0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913")

ERC20_ABI = [
    {
        "constant": True,
        "inputs": [{"name": "_owner", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "balance", "type": "uint256"}],
        "type": "function",
    },
    {
        "constant": True,
        "inputs": [],
        "name": "decimals",
        "outputs": [{"name": "", "type": "uint8"}],
        "type": "function",
    },
]

# ── Safety buffers ───────────────────────────────────────────────────────
# Never treat the full wallet balance as spendable. These are deliberately
# conservative — better to under-size than to have a fill fail on gas or
# leave the account at exactly zero.
MIN_ETH_FOR_GAS = 0.0003      # rough cost of a couple of fills' worth of gas
USDC_SAFETY_BUFFER = 0.05     # leave a few cents so rounding never breaks a fill

# ── Local, dependency-free transaction log ──────────────────────────────
# This is separate from (and does not depend on) the Firestore logging in
# ai_agent.py's _log_thetanuts_trade. Every fill attempt lands here first,
# so "every transaction is on record" holds even if Firestore is
# unconfigured, down, or misconfigured.
LOCAL_TX_LOG_PATH = Path(__file__).parent / "data" / "thetanuts_transactions.jsonl"


class ThetanutsTrader:
    def __init__(self):
        self.env = os.environ.copy()

        self.rpc_url = os.getenv("BASE_RPC_URL", DEFAULT_RPC_URL)
        self.private_key = os.getenv("WALLET_PRIVATE_KEY")

        self.w3 = None
        self.account = None
        self._init_error = None

        if not self.private_key:
            self._init_error = "WALLET_PRIVATE_KEY not set in environment — wallet features disabled."
            try:
                print(f"[ThetanutsTrader] {self._init_error}")
            except Exception:
                pass
            return

        try:
            self.w3 = Web3(Web3.HTTPProvider(self.rpc_url, request_kwargs={"timeout": 10}))
            self.account = Account.from_key(self.private_key)
            try:
                print(f"[ThetanutsTrader] Wallet loaded: {self.account.address} (RPC: {self.rpc_url})")
            except Exception:
                pass
        except Exception as e:
            self._init_error = f"Failed to initialize wallet/web3: {e}"
            try:
                print(f"[ThetanutsTrader] {self._init_error}")
            except Exception:
                pass

    # ──────────────────────────────────────────────────────────────────
    #  WALLET BALANCE
    # ──────────────────────────────────────────────────────────────────
    def get_wallet_balance(self) -> dict:
        """
        Reads the LIVE on-chain ETH + USDC balance for the configured
        wallet on Base Mainnet via a direct RPC call (no CLI round-trip).

        Never raises. On any failure returns ok=False with zeroed-out
        balances so callers (the AI agent, risk sizing, routes) degrade
        safely to "treat as no funds" rather than crashing or — worse —
        silently proposing a trade against a stale number.

        Returns:
          {
            ok, address, eth, usdc, tradable_usdc, has_gas, error
          }
        tradable_usdc is usdc minus a small safety buffer, and is forced
        to 0 if there isn't enough ETH in the wallet to pay for gas —
        there's no point telling the AI it has USDC to trade if the fill
        transaction can't even be submitted.
        """
        if self.w3 is None or self.account is None:
            return {
                "ok": False, "address": None, "eth": 0.0, "usdc": 0.0,
                "tradable_usdc": 0.0, "has_gas": False,
                "error": self._init_error or "Wallet not initialized.",
            }

        try:
            address = self.account.address

            eth_wei = self.w3.eth.get_balance(address)
            eth_balance = float(self.w3.from_wei(eth_wei, "ether"))

            usdc_contract = self.w3.eth.contract(address=USDC_BASE_ADDRESS, abi=ERC20_ABI)
            usdc_raw = usdc_contract.functions.balanceOf(address).call()
            usdc_decimals = usdc_contract.functions.decimals().call()
            usdc_balance = usdc_raw / (10 ** usdc_decimals)

            has_gas = eth_balance >= MIN_ETH_FOR_GAS
            tradable_usdc = max(0.0, round(usdc_balance - USDC_SAFETY_BUFFER, 6)) if has_gas else 0.0

            return {
                "ok": True,
                "address": address,
                "eth": round(eth_balance, 6),
                "usdc": round(usdc_balance, 4),
                "tradable_usdc": round(tradable_usdc, 4),
                "has_gas": has_gas,
                "error": None,
            }
        except Exception as e:
            return {
                "ok": False,
                "address": self.account.address if self.account else None,
                "eth": 0.0, "usdc": 0.0, "tradable_usdc": 0.0, "has_gas": False,
                "error": str(e),
            }

    # ──────────────────────────────────────────────────────────────────
    #  ORDERS
    # ──────────────────────────────────────────────────────────────────
    def get_live_orders(self, underlying: str = None, option_type: str = None, min_expiry: int = None) -> dict:
        """
        Fetch available orders from OptionBook via `thetanuts book orders`.
        Always returns {ok, data, error}.

        underlying / option_type / min_expiry map straight to the CLI's
        --underlying / --type / --min-expiry filters. Pass `underlying` so
        the list you get back only contains orders for the asset the swarm
        actually reasoned about — the caller should NOT just take index [0]
        of an unfiltered book.
        """
        cmd = ["npx", "@thetanuts-finance/cli", "book", "orders", "-o", "json"]
        if underlying:
            cmd += ["--underlying", underlying]
        if option_type:
            cmd += ["--type", option_type]
        if min_expiry:
            cmd += ["--min-expiry", str(min_expiry)]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True, text=True, env=self.env, timeout=30,
            )
            if result.returncode != 0:
                return {"ok": False, "data": [], "error": (result.stderr or "CLI exited non-zero").strip()}

            parsed = json.loads(result.stdout)
            # Normalize — the CLI may return a bare list or a wrapper object.
            if isinstance(parsed, list):
                orders = parsed
            else:
                orders = parsed.get("orders") or parsed.get("data") or []

            return {"ok": True, "data": orders, "error": None}

        except subprocess.TimeoutExpired:
            return {"ok": False, "data": [], "error": "CLI timed out fetching orders."}
        except json.JSONDecodeError as e:
            return {"ok": False, "data": [], "error": f"Could not parse CLI output as JSON: {e}"}
        except Exception as e:
            return {"ok": False, "data": [], "error": str(e)}

    # ──────────────────────────────────────────────────────────────────
    #  FILL / EXECUTE
    # ──────────────────────────────────────────────────────────────────
    def execute_fill(
        self,
        collateral_usdc: float,
        order_index: int = None,
        underlying: str = None,
        option_type: str = None,
        strike: float = None,
        strikes: str = None,
        expiry: int = None,
        approve_amount: str = None,
        scenarios: bool = False,
        strict: bool = False,
        dry_run: bool = True,
    ) -> dict:
        """
        Fill an OptionBook order via `thetanuts book fill`. Returns a
        structured record: { ok, status, tx_hash, error, raw_response, ... }
        status is one of: "EXECUTED", "DRY_RUN_OK", "FAILED".

        There is no `--order-id`/`--amount` — the real CLI takes either:
          - order_index: legacy index into the array `book orders` just
            returned. Only reliable if you pass it the SAME filters you
            passed to get_live_orders() (the CLI docs mark this "legacy"
            and describe it as an alternative to the selector below, not
            combinable with it) — VERIFY this against one real --dry-run
            call before trusting it live.
          - OR the explicit selector: underlying + option_type +
            (strike | strikes) + expiry, taken from the order you picked.
            This is the more robust path since it pins the exact contract
            instead of relying on array-position matching a possibly
            stale/reordered book.
        collateral_usdc is the USDC amount to spend on premium — the CLI
        derives contract count from the order price itself.

        Always passes --yes: `book fill` runs preview → allowance check →
        an INTERACTIVE confirm → send by default. Without --yes this
        subprocess has no stdin to answer that prompt and will just hang
        until the 60s timeout kills it — so a real trade would look like
        a generic timeout failure instead of a clean result either way.

        Every call — success, failure, or dry-run — is appended to the
        local JSONL transaction log before returning, so there is always
        a record on disk even if the caller never persists the result
        anywhere else.
        """
        has_index = order_index is not None
        has_selector = underlying and option_type and (strike is not None or strikes) and expiry
        if not has_index and not has_selector:
            return {
                "ok": False, "status": "FAILED", "tx_hash": None,
                "error": "Must provide either order_index, or underlying+option_type+strike(s)+expiry.",
            }

        cmd = [
            "npx", "@thetanuts-finance/cli", "book", "fill",
            "--collateral", str(collateral_usdc),
            "--yes",
            "-o", "json",
        ]
        if has_index:
            cmd += ["--order-index", str(order_index)]
        else:
            cmd += ["--underlying", underlying, "--type", option_type]
            if strikes:
                cmd += ["--strikes", strikes]
            else:
                cmd += ["--strike", str(strike)]
            cmd += ["--expiry", str(expiry)]
            if strict:
                cmd.append("--strict")
        if approve_amount:
            cmd += ["--approve-amount", str(approve_amount)]
        if scenarios:
            cmd.append("--scenarios")
        if dry_run:
            cmd.append("--dry-run")  # Always dry run first!

        record = {
            "order_index": order_index,
            "underlying": underlying,
            "option_type": option_type,
            "strike": strike,
            "strikes": strikes,
            "expiry": expiry,
            "collateral_usdc": collateral_usdc,
            "dry_run": dry_run,
            "ok": False,
            "status": "FAILED",
            "tx_hash": None,
            "error": None,
        }

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, env=self.env, timeout=60)

            if result.returncode != 0:
                record["error"] = (result.stderr or "CLI exited non-zero").strip()
                self._log_transaction(record)
                return record

            try:
                parsed = json.loads(result.stdout)
            except json.JSONDecodeError:
                record["error"] = f"Could not parse CLI output as JSON: {result.stdout[:300]}"
                self._log_transaction(record)
                return record

            record["ok"] = True
            record["status"] = "DRY_RUN_OK" if dry_run else "EXECUTED"
            record["tx_hash"] = parsed.get("txHash") or parsed.get("tx_hash")
            record["raw_response"] = parsed

            self._log_transaction(record)
            return record

        except subprocess.TimeoutExpired:
            record["error"] = "CLI timed out during fill."
            self._log_transaction(record)
            return record
        except Exception as e:
            record["error"] = str(e)
            self._log_transaction(record)
            return record

    # ──────────────────────────────────────────────────────────────────
    #  LOCAL TRANSACTION LOG
    # ──────────────────────────────────────────────────────────────────
    def _log_transaction(self, record: dict) -> None:
        """
        Appends one fill attempt to a local JSONL file. Deliberately has
        zero external dependencies (no DB, no network) so it can never be
        the reason a transaction goes unrecorded. Never raises.
        """
        try:
            LOCAL_TX_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
            entry = {
                **record,
                "wallet_address": self.account.address if self.account else None,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            with open(LOCAL_TX_LOG_PATH, "a") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception as e:
            print(f"⚠️ [ThetanutsTrader] Failed to write local tx log: {e}")

    def get_transaction_history(self, limit: int = 50) -> list:
        """Reads back the local JSONL log, most-recent-first."""
        if not LOCAL_TX_LOG_PATH.exists():
            return []
        try:
            lines = [l for l in LOCAL_TX_LOG_PATH.read_text().splitlines() if l.strip()]
            entries = [json.loads(l) for l in lines[-limit:]]
            return list(reversed(entries))
        except Exception as e:
            print(f"⚠️ [ThetanutsTrader] Failed to read local tx log: {e}")
            return []