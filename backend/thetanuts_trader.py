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
import shutil
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from web3 import Web3
from eth_account import Account

load_dotenv()

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
    {
        "constant": True,
        "inputs": [
            {"name": "_owner", "type": "address"},
            {"name": "_spender", "type": "address"},
        ],
        "name": "allowance",
        "outputs": [{"name": "", "type": "uint256"}],
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
        self.npx_command = shutil.which("npx.cmd") or shutil.which("npx")
        if not self.npx_command:
            raise RuntimeError("npx.cmd was not found on PATH")
        self.rpc_url = os.getenv("BASE_RPC_URL") or os.getenv("THETANUTS_RPC_URL") or DEFAULT_RPC_URL
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
    def get_live_orders(
        self,
        underlying: str = None,
        option_type: str = None,
        min_expiry: int = None,
    ) -> dict:
        """
        Fetch available orders from OptionBook via `thetanuts book orders`.

        Returns both:
          - raw on-chain values, preserved exactly
          - human-readable normalized values for AI/frontend use

        Thetanuts OptionBook JSON uses:
          - strikes: 8 decimals
          - pricePerContract: 8 decimals
          - availableAmount: 6 decimals
          - expiry: Unix timestamp seconds
        """
        cmd = [
            self.npx_command,
            "@thetanuts-finance/cli",
            "book",
            "orders",
            "-o",
            "json",
        ]
    
        if underlying:
            cmd += ["--underlying", str(underlying).upper()]
    
        if option_type:
            cmd += ["--type", str(option_type).upper()]
    
        if min_expiry is not None:
            cmd += ["--min-expiry", str(min_expiry)]
    
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                env=self.env,
                timeout=30,
            )
    
            if result.returncode != 0:
                return {
                    "ok": False,
                    "data": [],
                    "error": (
                        result.stderr
                        or result.stdout
                        or "CLI exited non-zero"
                    ).strip(),
                }
    
            try:
                parsed = json.loads(result.stdout)
            except json.JSONDecodeError as e:
                return {
                    "ok": False,
                    "data": [],
                    "error": f"Could not parse CLI output as JSON: {e}",
                }
    
            # CLI may return either a bare list or a wrapper object.
            if isinstance(parsed, list):
                raw_orders = parsed
            elif isinstance(parsed, dict):
                raw_orders = (
                    parsed.get("orders")
                    or parsed.get("data")
                    or []
                )
            else:
                raw_orders = []
    
            if not isinstance(raw_orders, list):
                raw_orders = []
    
            normalized_orders = []
    
            for order in raw_orders:
                if not isinstance(order, dict):
                    continue
                
                # ── Raw values ─────────────────────────────────────────
                raw_strikes = order.get("strikes")
                raw_price = order.get("pricePerContract")
                raw_available = order.get("availableAmount")
                raw_expiry = order.get("expiry")
    
                # ── Normalize strikes ─────────────────────────────────
                normalized_strikes = []
    
                if isinstance(raw_strikes, list):
                    for raw_strike in raw_strikes:
                        try:
                            normalized_strikes.append(
                                float(raw_strike) / 1e8
                            )
                        except (TypeError, ValueError):
                            pass
                        
                elif raw_strikes is not None:
                    try:
                        normalized_strikes.append(
                            float(raw_strikes) / 1e8
                        )
                    except (TypeError, ValueError):
                        pass
                    
                # ── Normalize price ───────────────────────────────────
                price_per_contract = None
    
                try:
                    if raw_price is not None:
                        price_per_contract = float(raw_price) / 1e8
                except (TypeError, ValueError):
                    pass
                
                # ── Normalize available amount ─────────────────────────
                available_contracts = None
    
                try:
                    if raw_available is not None:
                        available_contracts = float(raw_available) / 1e6
                except (TypeError, ValueError):
                    pass
                
                # ── Normalize expiry ──────────────────────────────────
                expiry = self._normalize_expiry(raw_expiry)
    
                # ── Option type ───────────────────────────────────────
                is_call = order.get("isCall")
    
                if is_call is True:
                    option_type_normalized = "CALL"
                elif is_call is False:
                    option_type_normalized = "PUT"
                else:
                    option_type_normalized = None
    
                # ── Underlying ─────────────────────────────────────────
                normalized_underlying = (
                    str(underlying).strip().upper()
                    if underlying
                    else order.get("underlying")
                )
    
                normalized_order = {
                    # Stable identity / human-readable values
                    "index": order.get("index"),
                    "underlying": normalized_underlying,
                    "option_type": option_type_normalized,
                    "strike": (
                        normalized_strikes[0]
                        if len(normalized_strikes) == 1
                        else None
                    ),
                    "strikes": normalized_strikes,
                    "expiry": expiry,
                    "price_per_contract": price_per_contract,
                    "available_contracts": available_contracts,
    
                    # Useful execution metadata
                    "maker": order.get("maker"),
                    "collateral": order.get("collateral"),
                    "implementation": order.get("implementation"),
                    "settlement": order.get("settlement"),
                    "is_long": order.get("isLong"),
                    "order_expiry_timestamp": order.get(
                        "orderExpiryTimestamp"
                    ),
    
                    # Preserve exact protocol values
                    "raw": {
                        "strikes": raw_strikes,
                        "pricePerContract": raw_price,
                        "availableAmount": raw_available,
                        "expiry": raw_expiry,
                    },
                }
    
                normalized_orders.append(normalized_order)
    
            return {
                "ok": True,
                "data": normalized_orders,
                "error": None,
            }
    
        except subprocess.TimeoutExpired:
            return {
                "ok": False,
                "data": [],
                "error": "CLI timed out fetching orders.",
            }
    
        except Exception as e:
            return {
                "ok": False,
                "data": [],
                "error": str(e),
            }

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
            self.npx_command,
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
            self.npx_command,
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
    #  WAIT FOR TRANSACTION
    # ──────────────────────────────────────────────────────────────────
    def wait_for_transaction(
        self,
        tx_hash: str,
        timeout: int = 120,
        poll_latency: float = 2.0,
    ) -> dict:
        """
        Wait for a submitted Base transaction to be mined.

        Returns:
            {
                ok,
                confirmed,
                tx_hash,
                block_number,
                receipt_status,
                error
            }

        receipt_status:
            1 = successful transaction
            0 = reverted transaction
        """
        if not tx_hash:
            return {
                "ok": False,
                "confirmed": False,
                "tx_hash": None,
                "block_number": None,
                "receipt_status": None,
                "error": "No transaction hash was returned by Thetanuts CLI.",
            }

        if self.w3 is None:
            return {
                "ok": False,
                "confirmed": False,
                "tx_hash": tx_hash,
                "block_number": None,
                "receipt_status": None,
                "error": (
                    self._init_error
                    or "Web3 connection is not initialized."
                ),
            }

        try:
            receipt = self.w3.eth.wait_for_transaction_receipt(
                tx_hash,
                timeout=timeout,
                poll_latency=poll_latency,
            )

            receipt_status = getattr(receipt, "status", None)

            # Web3.py receipt objects can also behave like dictionaries.
            if receipt_status is None:
                try:
                    receipt_status = receipt["status"]
                except Exception:
                    pass

            try:
                receipt_status = int(receipt_status)
            except (TypeError, ValueError):
                receipt_status = None

            block_number = getattr(receipt, "blockNumber", None)

            if block_number is None:
                try:
                    block_number = receipt["blockNumber"]
                except Exception:
                    pass

            if receipt_status != 1:
                return {
                    "ok": False,
                    "confirmed": True,
                    "tx_hash": tx_hash,
                    "block_number": block_number,
                    "receipt_status": receipt_status,
                    "error": (
                        "The Base transaction was mined but reverted."
                    ),
                }

            return {
                "ok": True,
                "confirmed": True,
                "tx_hash": tx_hash,
                "block_number": block_number,
                "receipt_status": 1,
                "error": None,
            }

        except Exception as e:
            return {
                "ok": False,
                "confirmed": False,
                "tx_hash": tx_hash,
                "block_number": None,
                "receipt_status": None,
                "error": str(e),
            }

        # ──────────────────────────────────────────────────────────────────
    #  VERIFY SELL
    # ──────────────────────────────────────────────────────────────────
    def verify_position_closed(
        self,
        underlying: str,
        option_type: str,
        strike: float,
        expiry: int,
        retries: int = 5,
        retry_delay: float = 3.0,
    ) -> dict:
        """
        Re-query LIVE Thetanuts positions after SELL.

        The transaction may already be mined while Thetanuts' position
        data has not updated yet, so retry several times.

        A SELL is considered successful only when the matching live
        position disappears.
        """
        import time

        last_result = None

        for attempt in range(retries):
            result = self.find_position(
                underlying=underlying,
                option_type=option_type,
                strike=strike,
                expiry=expiry,
            )

            last_result = result

            if not result["ok"]:
                return {
                    "ok": False,
                    "closed": False,
                    "position": None,
                    "attempt": attempt + 1,
                    "error": result["error"],
                }

            # Position has disappeared.
            if result["position"] is None:
                return {
                    "ok": True,
                    "closed": True,
                    "position": None,
                    "attempt": attempt + 1,
                    "error": None,
                }

            # Still visible. Give the indexer time to update.
            if attempt < retries - 1:
                time.sleep(retry_delay)

        return {
            "ok": True,
            "closed": False,
            "position": last_result.get("position") if last_result else None,
            "attempt": retries,
            "error": (
                "The transaction may be confirmed, but the live "
                "Thetanuts position is still present after verification retries."
            ),
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
        Fill an OptionBook order via a stable contract selector.

        Production execution deliberately does not accept order_index:
        OptionBook indexes are volatile and can point at a different
        contract after the book changes. The selector is always:
        underlying + option_type + strike(s) + expiry.

        The CLI is used for the live preview and for generating the exact
        approval/fill calldata. In live mode this method then:

          1. validates the wallet, chain, gas, and USDC balance;
          2. checks the allowance encoded by the CLI preview;
          3. sends approval only when the allowance is insufficient;
          4. waits for an approval receipt and requires status == 1;
          5. sends the OptionBook fill and waits for its receipt;
          6. requires the fill receipt status to equal 1.

        Every call — success, failure, or dry-run — is appended to the local
        JSONL transaction log before returning. Dry-run never signs, sends,
        or waits for a blockchain transaction.
        """
        # Keep the parameter for callers that still pass it, but never allow
        # the volatile index to reach either dry-run or production execution.
        if order_index is not None:
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
                "approval_tx_hash": None,
                "fill_tx_hash": None,
                "receipt_confirmed": False,
                "error": (
                    "order_index is not supported. Use the stable selector "
                    "underlying+option_type+strike(s)+expiry."
                ),
            }
            self._log_transaction(record)
            return record

        has_selector = (
            underlying is not None
            and option_type is not None
            and (strike is not None or strikes is not None)
            and expiry is not None
        )
        if not has_selector:
            record = {
                "order_index": None,
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
                "approval_tx_hash": None,
                "fill_tx_hash": None,
                "receipt_confirmed": False,
                "error": (
                    "Must provide underlying+option_type+strike(s)+expiry "
                    "for stable contract selection."
                ),
            }
            self._log_transaction(record)
            return record

        if collateral_usdc is None or collateral_usdc <= 0:
            record = {
                "order_index": None,
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
                "approval_tx_hash": None,
                "fill_tx_hash": None,
                "receipt_confirmed": False,
                "error": "collateral_usdc must be greater than 0 for BUY.",
            }
            self._log_transaction(record)
            return record

        cmd = [
            self.npx_command, "@thetanuts-finance/cli", "book", "fill",
            "--collateral", str(collateral_usdc),
            "--yes",
            "-o", "json",
        ]
        cmd += ["--underlying", str(underlying).upper(), "--type", str(option_type).upper()]
        if strikes:
            cmd += ["--strikes", str(strikes)]
        else:
            cmd += ["--strike", str(strike)]
        cmd += ["--expiry", str(expiry)]
        if strict:
            cmd.append("--strict")
        if approve_amount:
            cmd += ["--approve-amount", str(approve_amount)]
        if scenarios:
            cmd.append("--scenarios")

        # The CLI dry-run is the source of truth for the current quote and
        # calldata. It is also used immediately before a live submission so
        # the fill cannot rely on a stale preview from an earlier request.
        cmd.append("--dry-run")

        record = {
            "order_index": None,
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
            "approval_tx_hash": None,
            "fill_tx_hash": None,
            "receipt_confirmed": False,
            "error": None,
        }

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                env=self.env,
                timeout=60,
            )

            if result.returncode != 0:
                record["error"] = (
                    result.stderr
                    or result.stdout
                    or "Thetanuts CLI preview exited non-zero."
                ).strip()[:2000]
                self._log_transaction(record)
                return record

            try:
                parsed = json.loads((result.stdout or "").strip())
            except json.JSONDecodeError:
                record["error"] = f"Could not parse CLI output as JSON: {result.stdout[:300]}"
                self._log_transaction(record)
                return record

            if not isinstance(parsed, dict):
                record["error"] = "Thetanuts CLI preview did not return an object."
                self._log_transaction(record)
                return record

            record["raw_response"] = parsed
            record["preview"] = parsed.get("preview")
            record["approval"] = parsed.get("approve") or parsed.get("approval")
            record["fill"] = parsed.get("fill")

            # Dry-run ends here. In particular, do not call send_transaction,
            # do not wait for a receipt, and let callers avoid Firestore logs.
            if dry_run:
                record["ok"] = True
                record["status"] = "DRY_RUN_OK"
                self._log_transaction(record)
                return record

            if self.w3 is None or self.account is None:
                record["error"] = (
                    self._init_error
                    or "Wallet is not initialized; live BUY was blocked."
                )
                self._log_transaction(record)
                return record

            if self.w3.eth.chain_id != BASE_MAINNET_CHAIN_ID:
                record["error"] = (
                    f"Wrong network: connected to chain {self.w3.eth.chain_id}; "
                    f"expected Base Mainnet ({BASE_MAINNET_CHAIN_ID})."
                )
                self._log_transaction(record)
                return record

            wallet = self.get_wallet_balance()
            if not wallet.get("ok"):
                record["error"] = wallet.get("error") or "Unable to read wallet balance."
                self._log_transaction(record)
                return record
            if not wallet.get("has_gas"):
                record["error"] = "Insufficient Base ETH for transaction gas."
                self._log_transaction(record)
                return record
            if float(collateral_usdc) > float(wallet.get("tradable_usdc", 0.0) or 0.0):
                record["error"] = "Insufficient tradable USDC for this BUY."
                self._log_transaction(record)
                return record

            approval = record["approval"]
            approval_details = self._get_approval_details(approval)
            approval_tx_hash = None

            if approval is not None and approval_details is None:
                record["error"] = (
                    "Thetanuts CLI returned an incomplete USDC approval "
                    "payload; OptionBook fill was not sent."
                )
                self._log_transaction(record)
                return record

            if approval_details is not None:
                spender, required_amount = approval_details
                usdc = self.w3.eth.contract(address=USDC_BASE_ADDRESS, abi=ERC20_ABI)
                allowance = usdc.functions.allowance(
                    self.account.address,
                    spender,
                ).call()

                if allowance < required_amount:
                    approval_tx_hash = self._send_cli_transaction(
                        approval,
                        label="USDC approval",
                    )
                    record["approval_tx_hash"] = approval_tx_hash

                    approval_receipt = self.wait_for_transaction(
                        tx_hash=approval_tx_hash,
                        timeout=120,
                        poll_latency=2.0,
                    )
                    record["approval_receipt"] = approval_receipt

                    if not approval_receipt.get("ok"):
                        record["error"] = (
                            "USDC approval transaction failed; "
                            "OptionBook fill was not sent. "
                            f"{approval_receipt.get('error') or ''}".strip()
                        )
                        self._log_transaction(record)
                        return record

            fill = record["fill"]
            try:
                fill_tx_hash = self._send_cli_transaction(
                    fill,
                    label="OptionBook fill",
                )
            except Exception as e:
                record["error"] = f"Could not submit OptionBook fill: {e}"
                self._log_transaction(record)
                return record

            record["fill_tx_hash"] = fill_tx_hash
            record["tx_hash"] = fill_tx_hash

            fill_receipt = self.wait_for_transaction(
                tx_hash=fill_tx_hash,
                timeout=120,
                poll_latency=2.0,
            )
            record["fill_receipt"] = fill_receipt
            record["receipt_confirmed"] = bool(fill_receipt.get("confirmed"))

            if not fill_receipt.get("ok"):
                record["error"] = (
                    "The OptionBook fill transaction was mined but reverted."
                    if fill_receipt.get("confirmed")
                    else (
                        fill_receipt.get("error")
                        or "The OptionBook fill transaction was not confirmed."
                    )
                )
                self._log_transaction(record)
                return record

            record["ok"] = True
            record["status"] = "EXECUTED"
            record["error"] = None

            self._log_transaction(record)
            return record

        except subprocess.TimeoutExpired:
            record["error"] = "CLI timed out during live fill preview."
            self._log_transaction(record)
            return record
        except Exception as e:
            record["error"] = str(e)[:2000]
            self._log_transaction(record)
            return record

    @staticmethod
    def _get_approval_details(approval):
        """
        Extract (spender, amount) from the CLI-generated ERC-20 approve
        calldata. Returning None means the CLI did not request approval;
        this is the normal path when allowance is already sufficient.
        """
        if not isinstance(approval, dict):
            return None

        data = str(approval.get("data") or "").strip()
        to = approval.get("to")
        if not data or not to or not data.startswith("0x"):
            return None

        # approve(address,uint256) = 0x095ea7b3 followed by two 32-byte args.
        if data[:10].lower() != "0x095ea7b3" or len(data) < 138:
            raise ValueError("CLI approval payload is not ERC-20 approve calldata.")

        spender_word = data[10:74]
        amount_word = data[74:138]
        try:
            spender = Web3.to_checksum_address("0x" + spender_word[-40:])
            amount = int(amount_word, 16)
        except (TypeError, ValueError) as e:
            raise ValueError(f"Invalid CLI approval calldata: {e}") from e

        return spender, amount

    def _send_cli_transaction(self, payload: dict, label: str) -> str:
        """
        Submit calldata produced by the Thetanuts CLI.

        Nonce, chain id, gas limit, and fees are populated from the current
        Base RPC rather than trusting stale values from the preview.
        """
        if not isinstance(payload, dict):
            raise ValueError(f"{label} payload is missing from CLI preview.")

        to = payload.get("to")
        data = payload.get("data")
        if not to or not data:
            raise ValueError(f"{label} payload is missing 'to' or 'data'.")

        def _int_value(value):
            if value is None:
                return 0
            if isinstance(value, str):
                return int(value, 0) if value.lower().startswith("0x") else int(value)
            return int(value)

        tx = {
            "from": self.account.address,
            "to": Web3.to_checksum_address(to),
            "data": data,
            "value": _int_value(payload.get("value")),
            "chainId": BASE_MAINNET_CHAIN_ID,
            "nonce": self.w3.eth.get_transaction_count(
                self.account.address,
                "pending",
            ),
        }

        estimated_gas = self.w3.eth.estimate_gas(tx)
        tx["gas"] = max(21_000, int(estimated_gas * 1.20))

        latest_block = self.w3.eth.get_block("latest")
        base_fee = latest_block.get("baseFeePerGas")
        if base_fee is not None:
            priority_fee = getattr(self.w3.eth, "max_priority_fee", None)
            priority_fee = int(priority_fee or self.w3.to_wei(0.001, "gwei"))
            tx["maxPriorityFeePerGas"] = priority_fee
            tx["maxFeePerGas"] = int(base_fee * 2 + priority_fee)
        else:
            tx["gasPrice"] = self.w3.eth.gas_price

        signed = self.account.sign_transaction(tx)
        raw_transaction = getattr(signed, "raw_transaction", None)
        if raw_transaction is None:
            raw_transaction = signed.rawTransaction

        tx_hash = self.w3.eth.send_raw_transaction(raw_transaction)
        return tx_hash.hex()

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