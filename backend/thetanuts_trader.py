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
        if min_expiry is not None:
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
    #  POSITIONS
    # ──────────────────────────────────────────────────────────────────
    def get_positions(self, source: str = "all") -> dict:
        """
        Read the wallet's LIVE Thetanuts positions.

        source:
            all  -> book + rfq
            book -> OptionBook positions only
            rfq  -> RFQ positions only

        Read-only. Never signs or sends a transaction.
        """
        if self.w3 is None or self.account is None:
            return {
                "ok": False,
                "data": [],
                "error": self._init_error or "Wallet not initialized.",
            }

        if source not in ("all", "book", "rfq"):
            return {
                "ok": False,
                "data": [],
                "error": "source must be one of: all, book, rfq",
            }

        cmd = [
            "npx",
            "@thetanuts-finance/cli",
            "position",
            "list",
            "--address",
            self.account.address,
            "--source",
            source,
            "-o",
            "json",
        ]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                env=self.env,
                timeout=45,
            )

            if result.returncode != 0:
                return {
                    "ok": False,
                    "data": [],
                    "error": (
                        result.stderr
                        or "Thetanuts position list exited non-zero."
                    ).strip(),
                }

            try:
                parsed = json.loads(result.stdout)
            except json.JSONDecodeError as e:
                return {
                    "ok": False,
                    "data": [],
                    "error": f"Could not parse position list JSON: {e}",
                }

            if isinstance(parsed, list):
                positions = parsed

            elif isinstance(parsed, dict):
                positions = (
                    parsed.get("positions")
                    or parsed.get("data")
                    or []
                )

            else:
                positions = []

            if not isinstance(positions, list):
                positions = []

            return {
                "ok": True,
                "data": positions,
                "error": None,
            }

        except subprocess.TimeoutExpired:
            return {
                "ok": False,
                "data": [],
                "error": "CLI timed out fetching positions.",
            }

        except Exception as e:
            return {
                "ok": False,
                "data": [],
                "error": str(e),
            }

    @staticmethod
    def _normalize_expiry(value):
        """
        Normalize common Thetanuts expiry representations.

        Supports:
          - Unix timestamp
          - numeric string
          - ISO datetime string
        """
        if value is None:
            return None

        try:
            return int(float(value))
        except (TypeError, ValueError):
            pass

        if isinstance(value, str):
            try:
                normalized = value.strip()

                if normalized.endswith("Z"):
                    normalized = normalized[:-1] + "+00:00"

                dt = datetime.fromisoformat(normalized)

                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)

                return int(dt.timestamp())

            except (TypeError, ValueError, OverflowError):
                pass

        return None

    @staticmethod
    def _position_field(position: dict, *names):
        """Return the first non-None field from a position."""
        for name in names:
            value = position.get(name)
            if value is not None:
                return value
        return None

    def find_position(
        self,
        underlying: str,
        option_type: str,
        strike: float,
        expiry: int,
    ) -> dict:
        """
        Find the user's LIVE position matching the exact contract.

        Firestore is deliberately NOT used as the source of truth.

        Returns:
            {
                ok,
                position,
                matches,
                error
            }
        """
        result = self.get_positions("all")

        if not result["ok"]:
            return {
                "ok": False,
                "position": None,
                "matches": [],
                "error": result["error"],
            }

        positions = result["data"]

        underlying_norm = str(underlying).strip().upper()
        option_type_norm = str(option_type).strip().upper()

        try:
            target_strike = float(strike)
        except (TypeError, ValueError):
            return {
                "ok": False,
                "position": None,
                "matches": [],
                "error": f"Invalid strike: {strike}",
            }

        target_expiry = self._normalize_expiry(expiry)

        if target_expiry is None:
            return {
                "ok": False,
                "position": None,
                "matches": [],
                "error": f"Invalid expiry: {expiry}",
            }

        matches = []

        for position in positions:
            if not isinstance(position, dict):
                continue

            pos_underlying = self._position_field(
                position,
                "underlying",
                "asset",
                "underlyingAsset",
                "underlying_asset",
            )

            pos_type = self._position_field(
                position,
                "optionType",
                "type",
                "option_type",
                "option_type_name",
            )

            pos_strike = self._position_field(
                position,
                "strike",
                "strikePrice",
                "strike_price",
            )

            pos_expiry = self._position_field(
                position,
                "expiry",
                "expiration",
                "expirationTimestamp",
                "expiration_timestamp",
            )

            if pos_underlying is None or pos_type is None:
                continue

            if str(pos_underlying).strip().upper() != underlying_norm:
                continue

            if str(pos_type).strip().upper() != option_type_norm:
                continue

            try:
                if abs(float(pos_strike) - target_strike) > 1e-8:
                    continue
            except (TypeError, ValueError):
                continue

            normalized_pos_expiry = self._normalize_expiry(pos_expiry)

            if normalized_pos_expiry != target_expiry:
                continue

            matches.append(position)

        if not matches:
            return {
                "ok": True,
                "position": None,
                "matches": [],
                "error": None,
            }

        if len(matches) > 1:
            return {
                "ok": False,
                "position": None,
                "matches": matches,
                "error": (
                    "Multiple matching Thetanuts positions found. "
                    "SELL requires an unambiguous position."
                ),
            }

        return {
            "ok": True,
            "position": matches[0],
            "matches": matches,
            "error": None,
        }

    # ──────────────────────────────────────────────────────────────────
    #  SELL / CLOSE RFQ POSITION
    # ──────────────────────────────────────────────────────────────────
    def close_rfq_position(
        self,
        position_address: str,
        reserve_price: float = None,
        deadline_minutes: int = 1,
        fill_or_kill: bool = False,
        ensure_allowance: bool = False,
        approve_amount: str = None,
        dry_run: bool = True,
    ) -> dict:
        """
        Close an RFQ position using:

            thetanuts position close --address <option-contract>

        IMPORTANT:
        This operation is specifically for RFQ positions.

        dry_run=True is the default safety mode.
        """
        if not position_address:
            return {
                "ok": False,
                "status": "FAILED",
                "tx_hash": None,
                "error": "position_address is required.",
            }

        if deadline_minutes < 1:
            return {
                "ok": False,
                "status": "FAILED",
                "tx_hash": None,
                "error": "deadline_minutes must be >= 1.",
            }

        cmd = [
            "npx",
            "@thetanuts-finance/cli",
            "position",
            "close",
            "--address",
            str(position_address),
            "--deadline-minutes",
            str(deadline_minutes),
            "-o",
            "json",
        ]

        if reserve_price is not None:
            cmd += [
                "--reserve-price",
                str(reserve_price),
            ]

        if fill_or_kill:
            cmd.append("--fill-or-kill")

        if ensure_allowance:
            cmd.append("--ensure-allowance")

        if approve_amount is not None:
            cmd += [
                "--approve-amount",
                str(approve_amount),
            ]

        if dry_run:
            cmd.append("--dry-run")
        else:
            cmd.append("--yes")

        record = {
            "action": "SELL",
            "operation": "position_close",
            "position_address": position_address,
            "reserve_price": reserve_price,
            "deadline_minutes": deadline_minutes,
            "fill_or_kill": fill_or_kill,
            "ensure_allowance": ensure_allowance,
            "approve_amount": approve_amount,
            "dry_run": dry_run,
            "ok": False,
            "status": "FAILED",
            "tx_hash": None,
            "error": None,
        }

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                env=self.env,
                timeout=120,
            )

            stdout = (result.stdout or "").strip()
            stderr = (result.stderr or "").strip()

            if result.returncode != 0:
                record["error"] = (
                    stderr
                    or stdout
                    or "Thetanuts position close exited non-zero."
                )[:2000]

                self._log_transaction(record)
                return record

            try:
                parsed = json.loads(stdout)

            except json.JSONDecodeError:
                record["error"] = (
                    "Could not parse position close JSON: "
                    f"{stdout[:1000]}"
                )

                self._log_transaction(record)
                return record

            record["ok"] = True
            record["status"] = (
                "DRY_RUN_OK"
                if dry_run
                else "EXECUTED"
            )

            record["tx_hash"] = (
                parsed.get("txHash")
                or parsed.get("tx_hash")
                or parsed.get("transactionHash")
            )

            record["raw_response"] = parsed

            self._log_transaction(record)

            return record

        except subprocess.TimeoutExpired:
            record["error"] = (
                "CLI timed out during RFQ position close."
            )

            self._log_transaction(record)
            return record

        except Exception as e:
            record["error"] = str(e)

            self._log_transaction(record)
            return record

    # ──────────────────────────────────────────────────────────────────
    #  VERIFY SELL
    # ──────────────────────────────────────────────────────────────────
    def verify_position_closed(
        self,
        underlying: str,
        option_type: str,
        strike: float,
        expiry: int,
    ) -> dict:
        """
        Re-query LIVE Thetanuts positions after SELL.

        A SELL is considered fully successful only when the matching
        position disappears from the live position list.
        """
        result = self.find_position(
            underlying=underlying,
            option_type=option_type,
            strike=strike,
            expiry=expiry,
        )

        if not result["ok"]:
            return {
                "ok": False,
                "closed": False,
                "position": None,
                "error": result["error"],
            }

        return {
            "ok": True,
            "closed": result["position"] is None,
            "position": result["position"],
            "error": None,
        }

    # ──────────────────────────────────────────────────────────────────
    #  POSITION ADDRESS / SOURCE HELPERS
    # ──────────────────────────────────────────────────────────────────
    @staticmethod
    def get_position_source(position: dict) -> str:
        """
        Normalize the position source.

        Expected values:
            book
            rfq
        """
        if not isinstance(position, dict):
            return ""

        source = (
            position.get("source")
            or position.get("positionSource")
            or position.get("position_source")
            or ""
        )

        return str(source).strip().lower()

    @staticmethod
    def get_position_address(position: dict) -> str:
        """
        Extract the option contract address from CLI/indexer output.
        """
        if not isinstance(position, dict):
            return ""

        address = (
            position.get("address")
            or position.get("optionAddress")
            or position.get("option_address")
            or position.get("contractAddress")
            or position.get("contract_address")
            or ""
        )

        return str(address).strip()

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

        has_selector = (
            underlying is not None
            and option_type is not None
            and (strike is not None or strikes is not None)
            and expiry is not None
        )
        if not has_index and not has_selector:
            return {
                "ok": False, "status": "FAILED", "tx_hash": None,
                "error": "Must provide either order_index, or underlying+option_type+strike(s)+expiry.",
            }

        if collateral_usdc is None or collateral_usdc <= 0:
            return {
                "ok": False,
                "status": "FAILED",
                "tx_hash": None,
                "error": "collateral_usdc must be greater than 0 for BUY.",
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