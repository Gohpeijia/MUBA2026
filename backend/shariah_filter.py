import os
import requests

class shariahfilter:
    def __init__(self):
        self.api_key = os.getenv('FINNHUB_API_KEY')

        # ── Forbidden sectors ────────────────────────────────────────────────
        # "bank" and "finance" removed from top level — they're checked
        # AFTER the Islamic institution whitelist, so Maybank Islamic / BIMB
        # are no longer caught before the safe_words check runs.
        self.forbidden_keywords = [
            "gambling", "casino", "lottery", "betting", "maysir",
            "alcohol", "beer", "wine", "brewery", "distillery",
            "tobacco", "cigarette", "vape",
            "pork", "bacon",
            "pornography", "nightclub",
            "weapon", "arms", "defence contractor",
        ]

        # Conventional finance keywords — only checked when NOT an Islamic inst.
        self.conventional_finance_keywords = [
            "conventional bank", "interest income", "riba",
        ]

        # ── Islamic institution whitelist ────────────────────────────────────
        # Any of these in the combined name+industry = exempt from the
        # conventional-finance keyword block AND the debt ratio check,
        # because Islamic bank balance sheets structurally record customer
        # deposits as liabilities (inflating the D/E ratio unfairly).
        self.islamic_safe_words = [
            "islamic", "islam", "syariah", "shariah",
            "takaful", "bimb", "bsn", "agrobank", "bank rakyat",
            "muamalat", "affin islamic", "maybank islamic",
            "cimb islamic", "rhb islamic", "hong leong islamic",
        ]

    def _is_islamic_institution(self, combined_text: str) -> bool:
        return any(word in combined_text for word in self.islamic_safe_words)

    def check_compliance(self, ticker: str) -> dict:
        ticker = ticker.upper()
        try:
            # ── Fetch from Finnhub ───────────────────────────────────────────
            profile_url = (
                f"https://finnhub.io/api/v1/stock/profile2"
                f"?symbol={ticker}&token={self.api_key}"
            )
            metric_url = (
                f"https://finnhub.io/api/v1/stock/metric"
                f"?symbol={ticker}&metric=all&token={self.api_key}"
            )
            profile_data = requests.get(profile_url, timeout=5).json()
            metric_data  = requests.get(metric_url,  timeout=5).json()

            industry     = profile_data.get('finnhubIndustry', '').lower()
            company_name = profile_data.get('name', '').lower()
            combined     = f"{industry} {company_name}"

            is_islamic = self._is_islamic_institution(combined)

            # ── Step 1: Hard forbidden sectors (applies to everyone) ─────────
            for keyword in self.forbidden_keywords:
                if keyword in combined:
                    return {
                        "isHalal": False,
                        "reason":  f"Qualitative Failure: Involved in forbidden sector ({keyword}).",
                        "cash_ratio":  0.0,
                        "debt_ratio":  0.0,
                    }

            # ── Step 2: Conventional finance check (skip for Islamic inst.) ──
            if not is_islamic:
                for keyword in self.conventional_finance_keywords:
                    if keyword in combined:
                        return {
                            "isHalal": False,
                            "reason":  f"Qualitative Failure: Conventional interest-based finance ({keyword}).",
                            "cash_ratio": 0.0,
                            "debt_ratio": 0.0,
                        }

            # ── Step 3: Debt ratio check (skip for Islamic institutions) ─────
            # Islamic banks record customer deposits as liabilities, making
            # their D/E ratios structurally very high. Applying the 33% cap
            # to them would wrongly flag every Islamic bank as haram.
            metrics        = metric_data.get('metric', {})
            debt_to_equity = metrics.get('totalDebt/totalEquityAnnual')

            if not is_islamic:
                if debt_to_equity is None:
                    return {
                        "isHalal": False,
                        "reason":  "Financial data unavailable. Cannot verify compliance safely.",
                        "cash_ratio": 0.0,
                        "debt_ratio": 0.0,
                    }
                if debt_to_equity > 33.33:
                    return {
                        "isHalal": False,
                        "reason":  f"Quantitative Failure: Debt ratio {round(debt_to_equity, 2)}% exceeds 33.33% limit.",
                        "cash_ratio": 0.0,
                        "debt_ratio": round(debt_to_equity, 2),
                    }

            # ── Step 4: Pass ─────────────────────────────────────────────────
            islamic_note = " (Institusi Kewangan Islam — D/E dikecualikan)" if is_islamic else ""
            debt_display = round(debt_to_equity, 2) if debt_to_equity is not None else "N/A"
            return {
                "isHalal": True,
                "reason":  f"Halal. Lulus saringan sektor dan nisbah hutang ({debt_display}%){islamic_note}.",
                "cash_ratio":  0.0,
                "debt_ratio":  float(debt_to_equity) if debt_to_equity else 0.0,
            }

        except Exception as e:
            print(f"❌ Error screening {ticker}: {e}")
            return {
                "isHalal": False,
                "reason":  "API Connection Error",
                "cash_ratio": 0.0,
                "debt_ratio": 0.0,
            }


# Module-level singleton — one instance, not recreated per request
screener = shariahfilter()

def check_shariah_compliance(ticker: str) -> dict:
    return screener.check_compliance(ticker)