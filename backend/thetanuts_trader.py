import subprocess
import json
import os

class ThetanutsTrader:
    def __init__(self):
        self.env = os.environ.copy()

    def get_live_orders(self):
        """Fetch available orders from OptionBook in JSON format."""
        try:
            result = subprocess.run(
                ["npx", "@thetanuts-finance/cli", "orders", "-o", "json"],
                capture_output=True,
                text=True,
                env=self.env
            )
            return json.loads(result.stdout)
        except Exception as e:
            return {"error": str(e)}

    def execute_fill(self, order_id: str, amount: float, dry_run: bool = True):
        """Fill an OptionBook order (supports --dry-run)."""
        cmd = [
            "npx", "@thetanuts-finance/cli", "fill",
            "--order-id", str(order_id),
            "--amount", str(amount)
        ]
        if dry_run:
            cmd.append("--dry-run") # Always dry run first!

        result = subprocess.run(cmd, capture_output=True, text=True, env=self.env)
        return result.stdout