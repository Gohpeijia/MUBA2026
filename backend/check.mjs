import { ethers } from 'ethers';
import { ThetanutsClient } from '@thetanuts-finance/thetanuts-client';

const client = new ThetanutsClient({
  chainId: 8453,
  provider: new ethers.JsonRpcProvider(process.env.BASE_RPC_URL || process.env.THETANUTS_RPC_URL),
});

console.log((await client.api.fetchOrders()).length, 'live orders');
console.log(await client.api.getMarketData());