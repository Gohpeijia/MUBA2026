"""Read the local Anvil wallet; never submit a blockchain transaction."""
from urllib.parse import urlparse


def read_anvil_funding():
    from thetanuts_trader import ThetanutsTrader

    trader = ThetanutsTrader()
    if urlparse(trader.rpc_url).hostname not in ('localhost', '127.0.0.1', '::1'):
        raise ValueError('Stock simulation funding requires a local Anvil RPC URL.')
    if trader.w3 is None or trader.account is None:
        raise ValueError('Configure WALLET_PRIVATE_KEY for your Anvil account.')
    if 'anvil' not in trader.w3.client_version.lower():
        raise ValueError('Stock simulation funding requires an Anvil node.')
    # Simulated stock accounting only reads balances. Options execution
    # independently enforces Base chain ID 8453 before submitting fills.
    balance = trader.get_wallet_balance()
    if not balance.get('ok'):
        raise ValueError(balance.get('error') or 'Cannot read Anvil funding.')
    return balance
