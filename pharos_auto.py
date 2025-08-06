import asyncio
import json
import random
import sys
from datetime import datetime, timezone
from typing import Optional

import httpx  # 添加httpx导入
import time

import aiofiles
import curl_cffi.requests
import web3
from eth_account import Account
from eth_account.messages import encode_defunct
from fake_useragent import UserAgent
from web3 import AsyncWeb3
from loguru import logger

logger.remove()
logger.add(sys.stdout, format='<g>{time:YYYY-MM-DD HH:mm:ss:SSS}</g> | <c>{level}</c> | <level>{message}</level>')
Account.enable_unaudited_hdwallet_features()



task_id_dict = {
    '101': 'Zenith Swaps',
    '103': 'Send',
}

USDT_CONTRACT_ADDRESS = '0xD4071393f8716661958F766DF660033b3d35fD29'
USDC_CONTRACT_ADDRESS = '0x72df0bcd7276f2dFbAc900D1CE63c272C4BCcCED'

add_abi = [
    {
        "inputs": [
            {
                "components": [
                    {"internalType": "address", "name": "token0", "type": "address"},
                    {"internalType": "address", "name": "token1", "type": "address"},
                    {"internalType": "uint24", "name": "fee", "type": "uint24"},
                    {"internalType": "int24", "name": "tickLower", "type": "int24"},
                    {"internalType": "int24", "name": "tickUpper", "type": "int24"},
                    {"internalType": "uint256", "name": "amount0Desired", "type": "uint256"},
                    {"internalType": "uint256", "name": "amount1Desired", "type": "uint256"},
                    {"internalType": "uint256", "name": "amount0Min", "type": "uint256"},
                    {"internalType": "uint256", "name": "amount1Min", "type": "uint256"},
                    {"internalType": "address", "name": "recipient", "type": "address"},
                    {"internalType": "uint256", "name": "deadline", "type": "uint256"},
                ],
                "internalType": "struct INonfungiblePositionManager.MintParams",
                "name": "params",
                "type": "tuple",
            },
        ],
        "name": "mint",
        "outputs": [
            {"internalType": "uint256", "name": "tokenId", "type": "uint256"},
            {"internalType": "uint128", "name": "liquidity", "type": "uint128"},
            {"internalType": "uint256", "name": "amount0", "type": "uint256"},
            {"internalType": "uint256", "name": "amount1", "type": "uint256"},
        ],
        "stateMutability": "payable",
        "type": "function",
    },
]

ERC20_ABI = [
    {"constant": True, "inputs": [{"name": "_owner", "type": "address"}], "name": "balanceOf",
     "outputs": [{"name": "balance", "type": "uint256"}], "type": "function"},
    {"constant": True, "inputs": [], "name": "decimals", "outputs": [{"name": "", "type": "uint8"}],
     "type": "function"},
    {"constant": False, "inputs": [{"name": "_spender", "type": "address"}, {"name": "_value", "type": "uint256"}],
     "name": "approve", "outputs": [{"name": "success", "type": "bool"}], "type": "function"},
    {"constant": True, "inputs": [{"name": "_owner", "type": "address"}, {"name": "_spender", "type": "address"}],
     "name": "allowance", "outputs": [{"name": "", "type": "uint256"}], "type": "function"}
]


def truncate_round(number: float, digits: int = 0) -> float:
    multiplier = 10 ** digits
    return int(number * multiplier) / multiplier


def get_current_utc_time_formatted() -> str:
    """
    获取当前UTC时间并将其格式化为 YYYY-MM-DDTHH:MM:SS.sssZ 格式。

    Returns:
        格式化后的UTC时间字符串。
    """
    # 1. 获取带有时区信息的当前UTC时间
    utc_now = datetime.now(timezone.utc)

    # 2. 将时间格式化为 "YYYY-MM-DDTHH:MM:SS"
    formatted_time = utc_now.strftime('%Y-%m-%dT%H:%M:%S')

    # 3. 获取毫秒并格式化为三位数
    milliseconds = f".{utc_now.microsecond // 1000:03d}"

    # 4. 拼接字符串并添加 'Z' 来表示UTC
    return f"{formatted_time}{milliseconds}Z"


def get_amount(min_base_str='0.002', max_base_str='0.01', step_decimals=3):
    import random

    # --- 主要逻辑 (无需修改) ---
    PRECISION_DECIMALS = step_decimals
    # 计算整数乘数，用于转换
    multiplier_factor = 10 ** PRECISION_DECIMALS

    # 将浮点数区间转换为整数区间
    # 使用 int(float(...)) 来处理字符串输入
    min_multiplier = int(float(min_base_str) * multiplier_factor)
    max_multiplier = int(float(max_base_str) * multiplier_factor)

    # 在整数区间内生成一个随机乘数
    random_multiplier = random.randint(min_multiplier, max_multiplier)

    # 计算最终的 amount (纯整数运算)
    # 10**(18 - PRECISION_DECIMALS)
    wei_factor = 10 ** (18 - PRECISION_DECIMALS)
    amount = random_multiplier * wei_factor
    return amount


class Pharos:
    def __init__(self, mnemonic: str, proxy: str, invite: str, headers: dict, index, ilsh_config: dict):
        self.mnemonic = mnemonic
        self.proxy = proxy
        self.invite = invite
        self.index = index
        self.proxy_dict = {
            'http': self.proxy,
            'https': self.proxy
        }
        self.headers = headers
        self.session = curl_cffi.requests.AsyncSession(headers=self.headers, proxies=self.proxy_dict,
                                                       impersonate='chrome', verify=False)
        self.account = Account.from_mnemonic(self.mnemonic)

        self.my_invite_code = None
        self.onchain_enable = False
        self.x_id = None

        self.all_data: dict = {}
        self.w3: Optional[AsyncWeb3] = None
        self.account_statistic = None
        self.swap_task_items = []
        self.liquidity_task_items = []
        self.send_enable = False
        self.identity_service_enable = False
        self.nfts_enable = False
        self.enable_201 = False
        self.enable_202 = False
        self.enable_203 = False
        self.enable_204 = False
        self.verify_user_tasks = []
        self.send_times = 0
        self.zeith_swap_times = 0
        self.zeith_liq_times = 0
        self.faros_liq_times = 0
        self.faros_swap_times = 0
        self.usdc = 0
        self.usdt = 0
        self.interact_max = 91
        self.ilsh = ilsh_config

    async def init_web3(self):
        """初始化 Web3 连接"""
        self.w3 = AsyncWeb3(AsyncWeb3.AsyncHTTPProvider(
            endpoint_uri='https://testnet.dplabs-internal.com',
            request_kwargs={
                "proxy": self.proxy
            }
        ))

    async def login(self):
        """
        登录
        """
        nonce = await self.w3.eth.get_transaction_count(self.w3.to_checksum_address(self.account.address), 'pending')
        timestamp = get_current_utc_time_formatted()
        message = f"testnet.pharosnetwork.xyz wants you to sign in with your Ethereum account:\n{self.account.address}\n\nI accept the Pharos Terms of Service: testnet.pharosnetwork.xyz/privacy-policy/Pharos-PrivacyPolicy.pdf\n\nURI: https://testnet.pharosnetwork.xyz\n\nVersion: 1\n\nChain ID: 688688\n\nNonce: {nonce}\n\nIssued At: {timestamp}"
        signature = '0x' + self.account.sign_message(encode_defunct(text=message)).signature.hex()
        payload = {"address": self.account.address,
                   "signature": signature,
                   "wallet": "MetaMask", "nonce": str(nonce), "chain_id": "688688", "timestamp": timestamp,
                   "domain": "testnet.pharosnetwork.xyz"}
        print(payload)
        res = await self.session.post(f"https://api.pharosnetwork.xyz/user/login", json=payload)
        token = res.json()['data']['jwt']
        self.session.headers.update({
            'Authorization': f'Bearer {token}'
        })
        logger.success(f'{self.index}, {self.proxy}, 登陆成功')

    async def profile(self):
        """
        获取用户信息
        """
        try:
            res = await self.session.get(f"https://api.pharosnetwork.xyz/user/profile?address={self.account.address}")
            my_invite_code = res.json()['data']['user_info']['InviteCode']
            total_points = res.json()['data']['user_info']['TotalPoints']
            task_points = res.json()['data']['user_info']['TaskPoints']
            X_id = res.json()['data']['user_info']['XId']
            self.x_id = X_id

            self.my_invite_code = my_invite_code
            logger.info(
                f"{self.index}, {self.proxy}, Account: {self.account.address}, Total Points: {total_points}, Task Points: {task_points}")
            return total_points, task_points
        except Exception as e:
            print(e)

    async def interaction_statistic(self):
        logger.info(f'{self.index}, {self.proxy}, 检查账户交互信息')
        try:
            task_url = 'https://api.pharosnetwork.xyz/info/tasks'
            res = await self.session.get(task_url)
            if res.status_code == 200:
                onchain_task_dict = res.json().get('Onchain Tasks', {})
                onchain_tasks = onchain_task_dict.get('tasks', [])
                for task in onchain_tasks:
                    task_name = str(task.get('name'))
                    task_enable = task.get('enable')
                    if task_name == 'Swap' and task_enable:
                        self.swap_task_items = task.get('items', [])
                    elif task_name == 'Provide Liquidity' and task_enable:
                        self.liquidity_task_items = task.get('items', [])
                    elif task_name == 'Send To Friends' and task_enable:
                        self.send_enable = task_enable
                    elif task_name == 'Pharos Identity Service' and task_enable:
                        self.identity_service_enable = task_enable
                    elif task_name == 'Collect NFTs' and task_enable:
                        self.nfts_enable = task_enable
                social_task_dict = res.json().get('Social Tasks', {})
                social_tasks = social_task_dict.get('tasks', [])
                for task in social_tasks:
                    task_id = task['task_id']
                    task_enable = task['enable']
                    if task_id == 201:
                        self.enable_201 = task_enable
                    elif task_id == 202:
                        self.enable_202 = task_enable
                    elif task_id == 203:
                        self.enable_203 = task_enable
                    elif task_id == 204:
                        self.enable_204 = task_enable

            user_task_url = f'https://api.pharosnetwork.xyz/user/tasks?address={self.account.address}'
            res = await self.session.get(user_task_url)
            cur_all_ids = []
            if res.status_code == 200:
                user_tasks = res.json().get('data', {}).get('user_tasks', [])
                for task in user_tasks:
                    task_id = task.get('TaskId')
                    complete_times = task.get('CompleteTimes')
                    cur_all_ids.append(task_id)
                    if task_id == 201:
                        if complete_times is None or complete_times < 1:
                            self.verify_user_tasks.append(201)
                    elif task_id == 202:
                        if complete_times is None or complete_times < 1:
                            self.verify_user_tasks.append(202)
                    elif task_id == 203:
                        if complete_times is None or complete_times < 1:
                            self.verify_user_tasks.append(203)
                    elif task_id == 204:
                        if complete_times is None or complete_times < 1:
                            self.verify_user_tasks.append(204)
                    elif task_id == 103:
                        self.send_times = complete_times
                    elif task_id == 101:
                        self.zeith_swap_times = complete_times
                    elif task_id == 102:
                        self.zeith_liq_times = complete_times
                    elif task_id == 106:
                        self.faros_liq_times = complete_times
                    elif task_id == 107:
                        self.faros_swap_times = complete_times
            if 201 not in cur_all_ids:
                self.verify_user_tasks.append(201)
            if 202 not in cur_all_ids:
                self.verify_user_tasks.append(202)
            if 203 not in cur_all_ids:
                self.verify_user_tasks.append(203)
            if 204 not in cur_all_ids:
                self.verify_user_tasks.append(204)
        except Exception as e:
            print(e)

    async def tasks(self):
        """
        获取任务列表
        """
        try:
            res = await self.session.get(f"https://api.pharosnetwork.xyz/user/tasks?address={self.account.address}")
            return res.json()
        except Exception as e:
            print(e)

    async def check_in(self):
        """
        签到，先检查，后签到
        """
        logger.info(f'{self.index}, {self.proxy}, 签到检测')
        for i in range(10):
            try:
                check_in_status_res = await self.session.get(
                    f"https://api.pharosnetwork.xyz/sign/status?address={self.account.address}")
                status = check_in_status_res.json()['data']['status']

                # {"code":0,"data":{"status":"1111222"},"msg":"ok"}
                # 改为utc时区
                today = datetime.now(timezone.utc).weekday() + 1
                status_list = list(status)
                if status_list[today - 1] == '2':
                    check_in_res = await self.session.post(
                        f"https://api.pharosnetwork.xyz/sign/in?address={self.account.address}")
                    logger.success(f"{self.index}, {self.proxy}, Check-in result: {check_in_res.json()}")
                    if 'ok' in check_in_res.text:
                        logger.success(f'{self.index}, {self.proxy}, 签到成功！')
                        return
                elif status_list[today - 1] == '0':
                    logger.info(f'{self.index}, {self.proxy}, 今日已签到..')
                    return

            except Exception as e:
                logger.error(f'{self.index}, {self.proxy}, 签到失败：{e}')
                print(e)

    async def faucet_usdc_usdt(self):
        """
        获取USDC和USDT测试币
        """
        faucet_headers = {
            "accept": "*/*",
            "accept-encoding": "gzip, deflate, br, zstd",
            "accept-language": "zh-CN,zh;q=0.5",
            "content-type": "application/json",
            "origin": "https://testnet.zenithswap.xyz",
            "referer": "https://testnet.zenithswap.xyz/",
            "sec-ch-ua": "\"Chromium\";v=\"136\", \"Brave\";v=\"136\", \"Not.A/Brand\";v=\"99\"",
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": "\"macOS\"",
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-site",
            "sec-gpc": "1",
            "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36"
        }

        async with curl_cffi.requests.AsyncSession(headers=faucet_headers, proxies=self.proxy_dict) as faucet_session:
            payload = {"tokenAddress": "0xAD902CF99C2dE2f1Ba5ec4D642Fd7E49cae9EE37",
                       "userAddress": self.account.address}

            res = await faucet_session.post("https://testnet-router.zenithswap.xyz/api/v1/faucet", json=payload)
            logger.info(f"{self.index}, {self.proxy}, USDC/USDT faucet result: {res.json()}")

    async def faucet_PHRS(self):
        """
        获取PHRS测试币
        """
        logger.info(f'{self.index}, {self.proxy}, 开始PHRS测试币faucet')
        status_url = f"https://api.pharosnetwork.xyz/faucet/status?address={self.account.address}"
        status_res = await self.session.get(status_url)
        faucet_status = status_res.json()

        is_able_to_faucet = faucet_status['data']['is_able_to_faucet']
        logger.info(f"{self.index}, {self.proxy}, PHRS faucet status: {faucet_status}")

        if is_able_to_faucet:
            claim_url = f"https://api.pharosnetwork.xyz/faucet/daily"
            faucet_payload = {
                'address': self.account.address
            }
            res = await self.session.post(claim_url, json=faucet_payload)
            logger.success(f"{self.index}, {self.proxy}, PHRS claim result: {res.json()}")

    async def transfer(self):
        transfer_times = self.interact_max - self.send_times
        logger.info(f'{self.index}, {self.proxy}, 进行{transfer_times}次转账')
        for i in range(transfer_times):
            try:
                """
                ETH自转 - 自己给自己转ETH，使用随机gas防止女巫检测
                """
                # 获取ETH余额
                eth_balance = await self.w3.eth.get_balance(account=self.account.address)
                eth_balance_ether = self.w3.from_wei(eth_balance, 'ether')
                logger.info(f"{self.index}, {self.proxy}, Balance: {eth_balance_ether} PHRS")

                # 如果ETH余额不足，跳过转账
                if eth_balance < self.w3.to_wei(0.01, 'ether'):
                    logger.warning(f"{self.index}, {self.proxy}, ETH余额不足，跳过转账")
                    return

                # 随机转账金额 (0.0001 - 0.003 ETH)
                random_amount = 0.001
                send_amount_wei = self.w3.to_wei(random_amount, 'ether')
                # print(f"随机转账金额: {random_amount:.6f} PHRS")

                # 获取当前gas价格作为基准
                current_gas_price = await self.w3.eth.gas_price

                # 随机gas limit (21000 + 随机值，避免固定21000)
                base_gas = 21000
                random_gas_extra = random.randint(0, 5000)  # 0-5000额外gas
                random_gas_limit = base_gas + random_gas_extra

                # 随机gas price (基准价格的80%-150%)
                gas_price_multiplier = random.uniform(0.8, 1.5)
                random_gas_price = int(current_gas_price * gas_price_multiplier)

                # print(f"随机Gas Limit: {random_gas_limit}")
                # print(f"随机Gas Price: {random_gas_price} ({gas_price_multiplier:.2f}x)")

                tx = {
                    "to": self.account.address,
                    "value": send_amount_wei,
                    "nonce": await self.w3.eth.get_transaction_count(self.account.address, 'pending'),
                    "gas": random_gas_limit,
                    "gasPrice": random_gas_price,
                    "chainId": await self.w3.eth.chain_id
                }

                # print(f"交易详情: {tx}")

                # 签名并发送交易
                signed_txn = self.account.sign_transaction(tx)
                tx_hash = await self.w3.eth.send_raw_transaction(signed_txn.raw_transaction)

                logger.info(f"{self.index}, {self.proxy}, ETH自转交易已发送，交易哈希: {tx_hash.hex()}")

                # 等待交易确认
                receipt = await self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)

                if receipt.status == 1:
                    logger.success(f"{self.index}, {self.proxy}, ETH自转成功！交易哈希: {tx_hash.hex()}")
                    # print(f"实际Gas使用量: {receipt.gasUsed}")
                    # print(f"Gas费用: {receipt.gasUsed * random_gas_price / 10 ** 18:.8f} ETH")
                    verify_url = f"https://api.pharosnetwork.xyz/task/verify"
                    payload = {"address": self.account.address, "task_id": 103,
                               "tx_hash": '0x' + tx_hash.hex()}
                    # print(verify_url)
                    res = await self.session.post(url=verify_url, json=payload)
                    logger.info(f"{self.index}, {self.proxy}transfer验证结果: {res.text}")
                    await self.profile()
                    await self.tasks()

                else:
                    logger.warning(f"{self.index}, {self.proxy}, ETH自转失败！交易哈希: {tx_hash.hex()}")

            except Exception as e:
                logger.error(f"{self.index}, {self.proxy}, ETH自转出错: {str(e)}")
                import traceback
                traceback.print_exc()
            finally:
                await asyncio.sleep(random.uniform(6.5, 15.5))

    async def check_account_status(self):
        self.onchain_enable = True
        # # 检查redis缓存，避免频繁swap
        # redis_key = "pharos_swap"
        # account_key = self.account.address  # 或 self.mnemonic
        # last_swap_data = await redis_manager.get_hash_data(redis_key, account_key)
        # if last_swap_data:
        #     last_swap_time = float(last_swap_data.get('timestamp', 0))
        #     now = time.time()
        #     if now - last_swap_time < 24 * 3600:  # 4小时
        #         logger.warning(f"{self.index}, {self.proxy}, Account {self.account.address} swap too frequent, skip.")
        #         return
        #     else:
        #         self.onchain_enable = True
        # else:
        #     self.onchain_enable = True

    async def check_account_task_daily(self):
        address = self.account.address
        if address not in self.all_data:
            logger.info(f'{self.index}, {self.proxy}, 不存在于redis，运行！')
            return False
        current_data = self.all_data.get(address)
        run_timestamp = current_data['timestamp']
        run_diff_second = int(time.time()) - int(run_timestamp)
        hours = random.randint(6, 10)
        if run_diff_second < 60 * 60 * hours:
            logger.info(f'{self.index}, {self.proxy}, 距离上一次运行小于{hours}小时，不运行')
            return True
        else:
            print(f'{self.index}, {self.proxy}, 运行账号！')
            return False

    async def check_nft_balance(self, contract='0x1da9f40036bee3fda37ddd9bff624e1125d8991d'):
        """
        检查账号是否已经拥有NFT（判断是否已mint）
        """
        try:
            mint_contract = contract

            # ERC721标准的balanceOf函数ABI
            balance_abi = [
                {
                    "inputs": [{"name": "owner", "type": "address"}],
                    "name": "balanceOf",
                    "outputs": [{"name": "", "type": "uint256"}],
                    "stateMutability": "view",
                    "type": "function"
                }
            ]

            # 创建合约实例
            contract = self.w3.eth.contract(address=self.w3.to_checksum_address(mint_contract), abi=balance_abi)

            # 调用balanceOf函数
            balance = await contract.functions.balanceOf(self.account.address).call()

            logger.info(f"{self.index}, {self.proxy}, Account {self.account.address} NFT balance: {balance}")

            return balance > 0  # 如果余额大于0，说明已经mint了

        except Exception as e:
            logger.error(f"{self.index}, {self.proxy}, 检查NFT余额失败: {str(e)}")
            # 如果检查失败，返回False，允许尝试mint
            return False

    async def mint(self):
        """
        执行mint操作
        """
        try:
            logger.info(f'{self.index}, {self.proxy}, 开始NFT检测')
            # 检查是否已经mint过NFT
            nft_minted = await self.check_nft_balance()
            if nft_minted is True:
                logger.success(f"{self.index}, {self.proxy}, 账号 {self.account.address} 已经拥有NFT，跳过mint操作")
                return "already_minted"

            logger.info(f"{self.index}, {self.proxy}, 账号 {self.account.address} 尚未mint，开始mint操作...")

            # 获取账户余额
            balance = await self.w3.eth.get_balance(self.account.address)
            balance_ether = self.w3.from_wei(balance, 'ether')
            # print(f"Current balance: {balance_ether} ETH")
            # 检查余额是否足够支付gas费用和可能的ETH转账
            min_balance_required = self.w3.to_wei(1.2, 'ether')  # 至少需要0.02 ETH
            if balance < min_balance_required:
                logger.warning(
                    f"{self.index}, {self.proxy}, 余额不足，需要至少 1.2 ETH，当前余额: {balance_ether:.6f} ETH")
                return

            mint_contract = "0x1da9f40036bee3fda37ddd9bff624e1125d8991d"
            temp_data = '##############'.lower()
            # 你提供的inputdata
            input_data = "0x84bb1e42000000000000000000000000##############0000000000000000000000000000000000000000000000000000000000000001000000000000000000000000eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee0000000000000000000000000000000000000000000000000de0b6b3a764000000000000000000000000000000000000000000000000000000000000000000c0000000000000000000000000000000000000000000000000000000000000016000000000000000000000000000000000000000000000000000000000000000800000000000000000000000000000000000000000000000000000000000000000ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            # 替换地址（重要：需要重新赋值）
            input_data = input_data.replace(temp_data, str(self.account.address).lower().replace('0x', ''))
            # print(f"替换后的input_data: {input_data[:100]}...")  # 打印前100个字符用于验证

            # 获取当前gas价格
            gas_price = await self.w3.eth.gas_price

            # 估算gas limit
            try:
                # 构建交易用于估算gas
                tx_for_estimate = {
                    'from': self.w3.to_checksum_address(self.account.address),
                    'to': self.w3.to_checksum_address(mint_contract),
                    'data': input_data,
                    'value': self.w3.to_wei(1, 'ether'),  # inputdata中包含1 ETH的值
                }

                estimated_gas = await self.w3.eth.estimate_gas(tx_for_estimate)
                gas_limit = int(estimated_gas * 1.2)  # 增加20%作为缓冲
                # print(f"估算Gas Limit: {gas_limit}")

            except Exception as e:
                # print(f"Gas估算失败:{e}")
                return

            # 构建完整交易
            transaction = {
                'from': self.w3.to_checksum_address(self.account.address),
                'to': self.w3.to_checksum_address(mint_contract),
                'data': input_data,
                'value': self.w3.to_wei(1, 'ether'),  # 从inputdata分析出需要发送1 ETH
                'gas': gas_limit,
                'gasPrice': gas_price,
                'nonce': await self.w3.eth.get_transaction_count(self.w3.to_checksum_address(self.account.address),
                                                                 'pending'),
                'chainId': await self.w3.eth.chain_id
            }

            # print(f"Mint交易详情: to={mint_contract}, value=1 ETH, gas={gas_limit}")

            # 签名交易
            signed_txn = self.account.sign_transaction(transaction)

            # 发送交易
            tx_hash = await self.w3.eth.send_raw_transaction(signed_txn.raw_transaction)
            # print(f"Mint交易已发送，交易哈希: {tx_hash.hex()}")

            # 等待交易确认
            receipt = await self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=300)

            if receipt.status == 1:
                logger.success(f"{self.index}, {self.proxy}, Mint成功！交易哈希: {tx_hash.hex()}")
                # print(f"Gas使用量: {receipt.gasUsed}")
                # print(f"Gas费用: {receipt.gasUsed * gas_price / 10 ** 18:.8f} ETH")

                return tx_hash.hex()
            else:
                logger.error(f"{self.index}, {self.proxy}, Mint失败！交易哈希: {tx_hash.hex()}")
                return None

        except Exception as e:
            logger.error(f"{self.index}, {self.proxy}, Mint操作出错: {str(e)}")
            import traceback
            traceback.print_exc()
            return None

    async def faros_swap(self):
        swap_count = self.interact_max - self.faros_swap_times
        logger.info(f'{self.index}, {self.proxy}, 进行{swap_count}次faros swap')
        for i in range(swap_count):
            try:
                headers = {
                    'accept': 'application/json, text/plain, */*',
                    'accept-language': 'zh-CN,zh;q=0.8',
                    'origin': 'https://faroswap.xyz',
                    'priority': 'u=1, i',
                    'referer': 'https://faroswap.xyz/',
                    'sec-ch-ua-mobile': '?0',
                    'sec-ch-ua-platform': '"macOS"',
                    'sec-fetch-dest': 'empty',
                    'sec-fetch-mode': 'cors',
                    'sec-fetch-site': 'cross-site',
                    'sec-gpc': '1',
                }
                deadline = int(time.time()) + 600
                slippage = random.choice([10.401, 10.301, 5.301, 12.301])

                # 直接生成一个在 wei 范围内的随机整数
                amount = get_amount()
                # print(f'faros swap， 滑点:{slippage}, amount:{amount}')
                to_token_address = random.choice(
                    ['0xD4071393f8716661958F766DF660033b3d35fD29', '0x72df0bcd7276f2dFbAc900D1CE63c272C4BCcCED'])
                get_swap_route_url = f'https://api.dodoex.io/route-service/v2/widget/getdodoroute?chainId=688688&deadLine={deadline}&apikey=a37546505892e1a952&slippage={str(slippage)}&source=dodoV2AndMixWasm&toTokenAddress={to_token_address}&fromTokenAddress=0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE&userAddr={self.account.address}&estimateGas=true&fromAmount={str(amount)}'

                proxies = {
                    'http://': self.proxy,
                    'https://': self.proxy,
                }
                async with httpx.AsyncClient(headers=headers, proxies=proxies, verify=False) as session:

                    res = await session.get(get_swap_route_url)

                    if res.status_code == 200:
                        input_data = res.json()['data']['data']
                        gas_limit = res.json()['data']['gasLimit']
                        logger.success(f'{self.index}, {self.proxy}, dodo api请求成功：gas limit:{gas_limit}')
                        contract_address = '0x3541423f25a1ca5c98fdbcf478405d3f0aad1164'
                        gas = int(int(gas_limit) * random.uniform(1.2, 1.5))

                        swap_tx = {
                            "to": self.w3.to_checksum_address(contract_address),
                            "from": self.account.address,
                            "data": input_data,
                            "value": amount,
                            "gas": gas,
                            "gasPrice": self.w3.to_wei(1, "gwei"),
                            "nonce": await self.w3.eth.get_transaction_count(self.account.address, "pending"),
                            "chainId": await self.w3.eth.chain_id
                        }
                        # print('swap_tx', swap_tx)
                        signed_tx = self.w3.eth.account.sign_transaction(swap_tx, self.account.key)
                        raw_tx = await self.w3.eth.send_raw_transaction(signed_tx.raw_transaction)
                        tx_hash = self.w3.to_hex(raw_tx)
                        receipt = await self.w3.eth.wait_for_transaction_receipt(tx_hash)
                        if receipt.status == 1:
                            logger.success(
                                f"{self.index}, {self.proxy}, faros swap成功! tx: {tx_hash}, 区块号: {receipt.blockNumber}")
            except Exception as e:
                logger.error(f'{self.index}, {self.proxy}, faros swap error:{e}')
            finally:
                logger.info(f'{self.index}, {self.proxy}, 完成第{i}/{swap_count}次交互，等待下一波')
                await asyncio.sleep(random.uniform(8.5, 11.5))

    async def approve_token(self, token_contract, amount, decimals, to_contract_address):
        try:
            amount_wei = 2 ** 256 - 1
            # 检查授权
            allowance = await token_contract.functions.allowance(
                self.w3.to_checksum_address(self.account.address),
                self.w3.to_checksum_address(to_contract_address)
            ).call()
            if allowance >= amount_wei:
                logger.info(f"{self.index}, {self.proxy}, 已授权: {allowance / (10 ** decimals)}")
                return True
            gas = await token_contract.functions.approve(
                self.w3.to_checksum_address(to_contract_address),
                amount_wei
            ).estimate_gas({'from': self.w3.to_checksum_address(self.account.address)})
            multiple_gas = round(random.uniform(1.01, 1.2), 2)
            gas = int(gas * multiple_gas)
            gas_price = await self.w3.eth.gas_price
            eth_balance = await self.w3.eth.get_balance(self.account.address)
            if gas * gas_price > eth_balance:
                logger.error(f"{self.index}, {self.proxy}, ETH 余额不足: {eth_balance / 10 ** 18} ETH")
                return None
            tx = await token_contract.functions.approve(
                self.w3.to_checksum_address(to_contract_address),
                amount_wei
            ).build_transaction({
                'from': self.w3.to_checksum_address(self.account.address),
                'nonce': await self.w3.eth.get_transaction_count(self.account.address, "pending"),
                'gas': gas,
                'gasPrice': gas_price
            })
            signed_tx = self.w3.eth.account.sign_transaction(tx, self.account.key)
            tx_hash = await self.w3.eth.send_raw_transaction(signed_tx.raw_transaction)
            receipt = await self.w3.eth.wait_for_transaction_receipt(tx_hash)
            logger.info(
                f"{self.index}, {self.proxy}, 授权成功: {self.w3.to_hex(tx_hash)}, blockNumber:{receipt.blockNumber}")
            return receipt
        except Exception as e:
            logger.error(f"{self.index}, {self.proxy}, 授权失败: {e}")
            return None

    async def add_liq(self):
        liq_count = self.interact_max - self.zeith_liq_times
        for i in range(liq_count):
            logger.info(f"{self.index}, {self.proxy}, zeith添加流动性")
            add_contract_address = '0xf8a1d4ff0f9b9af7ce58e1fc1833688f3bfd6115'
            token0 = USDC_CONTRACT_ADDRESS
            token1 = USDT_CONTRACT_ADDRESS
            # 获取当前价格
            price, sqrt_price_x96, current_tick = await self.get_pool_price(token0, token1)
            if price is None or sqrt_price_x96 is None or current_tick is None:
                logger.error(f"{self.index}, {self.proxy}, 获取池子价格失败，无法添加流动性")
                return

            try:
                self.usdc, usdc_decimals = await self.check_token_balance(contract_address=USDC_CONTRACT_ADDRESS)
                self.usdt, usdt_decimals = await self.check_token_balance(contract_address=USDT_CONTRACT_ADDRESS)
                token0_decimals = usdc_decimals
                token1_decimals = usdt_decimals
                logger.info(f'{self.index}, {self.proxy}, 账户余额usdc：{self.usdc}，usdt: {self.usdt}')
                if float(self.usdt) > 0.0 and float(self.usdc) > 0.0:
                    logger.info(f"{self.index}, {self.proxy}, 当前usdc、usdt余额均大于0，可以添加流动性。")
                else:
                    logger.warning(f"{self.index}, {self.proxy}, 当前usdc、usdt余额存在小于0，不添加流动性。")
                    return
                amount0 = round(min(self.usdc, self.usdt) * 0.25, 3)  # 使用余额的 25% 或默认值
                if amount0 > 10.0:
                    amount0 = round(amount0 / 10, 3)
                tick_lower = -887270
                tick_upper = 887270

                if token0.lower() > token1.lower():
                    logger.error(f'{self.index}, {self.proxy}, liq 合约大小错误，token0:{token0}, token1:{token1}')
                    return
                amount0_desired = amount0 * 10 ** token0_decimals
                amount1_desired = amount0 * price * 10 ** token1_decimals
                logger.info(
                    f"{self.index}, {self.proxy}, amount0: {amount0}, amount0Desired: {amount0_desired} ==> amount1Desired: {amount1_desired}")

                # 授权代币
                token0_contract = self.w3.eth.contract(address=self.w3.to_checksum_address(token0), abi=ERC20_ABI)
                token1_contract = self.w3.eth.contract(address=self.w3.to_checksum_address(token1), abi=ERC20_ABI)
                logger.info(f"{self.index}, {self.proxy}, 授权 USDC...")
                receipt0 = await self.approve_token(token0_contract, amount0, usdc_decimals,
                                                    to_contract_address=add_contract_address)
                if not receipt0:
                    return
                logger.info(f"{self.index}, {self.proxy}, 授权 USDT...")
                amount1 = amount1_desired / (10 ** usdt_decimals)
                receipt1 = await self.approve_token(token1_contract, amount1, usdt_decimals,
                                                    to_contract_address=add_contract_address)
                if not receipt1:
                    return
                add_contract = self.w3.eth.contract(address=self.w3.to_checksum_address(add_contract_address),
                                                    abi=add_abi)
                add_tx = {
                    "token0": self.w3.to_checksum_address(token0),
                    "token1": self.w3.to_checksum_address(token1),
                    "fee": 500,
                    "tickLower": tick_lower,
                    "tickUpper": tick_upper,
                    "amount0Desired": int(amount0_desired),
                    "amount1Desired": int(amount1_desired),
                    "amount0Min": int(amount0_desired * (1 - 0.5 / 100)),
                    "amount1Min": int(amount1_desired * (1 - 0.5 / 100)),
                    "recipient": self.w3.to_checksum_address(self.account.address),
                    "deadline": int(time.time()) + 600
                }
                # 预估gas
                gas = await add_contract.functions.mint(add_tx).estimate_gas({
                    'from': self.w3.to_checksum_address(self.account.address)
                })
                multiple_gas = round(random.uniform(1.01, 1.2), 2)
                gas = int(gas * multiple_gas)  # 增加 20% 缓冲
                gas_price = await self.w3.eth.gas_price
                tx = await add_contract.functions.mint(add_tx).build_transaction({
                    "from": self.w3.to_checksum_address(self.account.address),
                    "gas": gas,
                    "gasPrice": gas_price,
                    "nonce": await self.w3.eth.get_transaction_count(self.w3.to_checksum_address(self.account.address),
                                                                     'pending'),
                    "chainId": await self.w3.eth.chain_id
                })
                signed_tx = self.w3.eth.account.sign_transaction(tx, self.account.key)
                tx_hash = await self.w3.eth.send_raw_transaction(signed_tx.raw_transaction)
                receipt = await self.w3.eth.wait_for_transaction_receipt(tx_hash)
                if receipt.status == 1:
                    logger.success(
                        f"{self.index}, {self.proxy}, zenith liq添加完成: {self.w3.to_hex(tx_hash)}, blockNumber:{receipt.blockNumber}")


            except Exception as e:
                logger.error(f'{self.index}, {self.proxy}, add zenith liq失败:{e}')
            finally:
                logger.info(f'{self.index}, {self.proxy}, 已完成：{i}/{liq_count}, 睡眠等待下一波')
                await asyncio.sleep(random.randint(10, 15))

    async def do_task(self):
        logger.info(f'{self.index}, {self.proxy}, 当前未完成任务ids：{self.verify_user_tasks}')
        url = "https://api.pharosnetwork.xyz/task/verify"
        for task_id in self.verify_user_tasks:
            try:
                payload = {"address": self.account.address, "task_id": task_id}
                res = await self.session.post(url, json=payload)
                if res.status_code == 200:
                    logger.info(f'{self.index}, {self.proxy}, 社交任务验证结果：{res.text}')
                    if res.json()['code'] == 1:
                        logger.warning(f'{self.index}, {self.proxy}, 当前账号未绑定推特/DC')
                    elif res.json()['data']['verified']:
                        logger.success(f'{self.index}, {self.proxy}, 社交任务验证成功. task_id: {task_id}')
                else:
                    logger.warning(
                        f'{self.index}, {self.proxy}, 社交任务验证失败. task_id: {task_id}, code:{res.status_code} error:{res.text}')
            except Exception as e:
                logger.error(f'{self.index}, {self.proxy}, 社交任务验证失败：{e}. task_id: {task_id}')

    async def mint_faro_badge(self):
        mint_contract = '0x7fb63bfd3ef701544bf805e88cb9d2efaa3c01a9'

        input_data = "0x84bb1e42000000000000000000000000##############0000000000000000000000000000000000000000000000000000000000000001000000000000000000000000eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee0000000000000000000000000000000000000000000000000de0b6b3a764000000000000000000000000000000000000000000000000000000000000000000c0000000000000000000000000000000000000000000000000000000000000016000000000000000000000000000000000000000000000000000000000000000800000000000000000000000000000000000000000000000000000000000000000ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"

        """
        执行mint操作
        """
        try:
            logger.info(f'{self.index}, {self.proxy}, 开始faro NFT检测')
            # 检查是否已经mint过NFT
            nft_minted = await self.check_nft_balance(contract=mint_contract)
            if nft_minted is True:
                logger.success(f"{self.index}, {self.proxy}, 账号 {self.account.address} 已经拥有faro NFT，跳过mint操作")
                return "already_minted"

            logger.info(f"{self.index}, {self.proxy}, 账号 {self.account.address} faro 尚未mint，开始mint操作...")

            # 获取账户余额
            balance = await self.w3.eth.get_balance(self.account.address)
            balance_ether = self.w3.from_wei(balance, 'ether')
            # print(f"Current balance: {balance_ether} ETH")
            # 检查余额是否足够支付gas费用和可能的ETH转账
            min_balance_required = self.w3.to_wei(1.2, 'ether')  # 至少需要0.02 ETH
            if balance < min_balance_required:
                logger.warning(
                    f"{self.index}, {self.proxy}, 余额不足，faro NFT 需要至少 1.2 ETH，当前余额: {balance_ether:.6f} ETH")
                return

            temp_data = '##############'.lower()
            # 你提供的inputdata
            # 替换地址（重要：需要重新赋值）
            input_data = input_data.replace(temp_data, str(self.account.address).lower().replace('0x', ''))
            # print(f"替换后的input_data: {input_data[:100]}...")  # 打印前100个字符用于验证

            # 获取当前gas价格
            gas_price = await self.w3.eth.gas_price

            # 估算gas limit
            try:
                # 构建交易用于估算gas
                tx_for_estimate = {
                    'from': self.w3.to_checksum_address(self.account.address),
                    'to': self.w3.to_checksum_address(mint_contract),
                    'data': input_data,
                    'value': self.w3.to_wei(1, 'ether'),  # inputdata中包含1 ETH的值
                }

                estimated_gas = await self.w3.eth.estimate_gas(tx_for_estimate)
                gas_limit = int(estimated_gas * round(random.uniform(1.1, 1.5), 2))  # 增加20%作为缓冲
                # print(f"估算Gas Limit: {gas_limit}")

            except Exception as e:
                # print(f"Gas估算失败:{e}")
                return

            # 构建完整交易
            transaction = {
                'from': self.w3.to_checksum_address(self.account.address),
                'to': self.w3.to_checksum_address(mint_contract),
                'data': input_data,
                'value': self.w3.to_wei(1, 'ether'),  # 从inputdata分析出需要发送1 ETH
                'gas': gas_limit,
                'gasPrice': gas_price,
                'nonce': await self.w3.eth.get_transaction_count(self.w3.to_checksum_address(self.account.address),
                                                                 'pending'),
                'chainId': await self.w3.eth.chain_id
            }

            # print(f"Mint交易详情: to={mint_contract}, value=1 ETH, gas={gas_limit}")

            # 签名交易
            signed_txn = self.account.sign_transaction(transaction)

            # 发送交易
            tx_hash = await self.w3.eth.send_raw_transaction(signed_txn.raw_transaction)
            # print(f"Mint交易已发送，交易哈希: {tx_hash.hex()}")

            # 等待交易确认
            receipt = await self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=300)

            if receipt.status == 1:
                logger.success(f"{self.index}, {self.proxy}, Mint成功！交易哈希: {tx_hash.hex()}")
                # print(f"Gas使用量: {receipt.gasUsed}")
                # print(f"Gas费用: {receipt.gasUsed * gas_price / 10 ** 18:.8f} ETH")

                return tx_hash.hex()
            else:
                logger.error(f"{self.index}, {self.proxy}, faro Mint失败！交易哈希: {tx_hash.hex()}")
                return None

        except Exception as e:
            logger.error(f"{self.index}, {self.proxy}, faro Mint操作出错: {str(e)}")
            import traceback
            traceback.print_exc()
            return None

    async def mint_pharos_badge2(self):
        mint_contract = '0x2a469a4073480596b9deb19f52aa89891ccff5ce'

        input_data = "0x84bb1e42000000000000000000000000##############0000000000000000000000000000000000000000000000000000000000000001000000000000000000000000eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee0000000000000000000000000000000000000000000000000de0b6b3a764000000000000000000000000000000000000000000000000000000000000000000c0000000000000000000000000000000000000000000000000000000000000016000000000000000000000000000000000000000000000000000000000000000800000000000000000000000000000000000000000000000000000000000000000ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
        """
        执行mint操作
        """
        try:
            logger.info(f'{self.index}, {self.proxy}, 开始faro NFT检测')
            # 检查是否已经mint过NFT
            nft_minted = await self.check_nft_balance(contract=mint_contract)
            if nft_minted is True:
                logger.success(f"{self.index}, {self.proxy}, 账号 {self.account.address} 已经拥有faro NFT，跳过mint操作")
                return "already_minted"

            logger.info(f"{self.index}, {self.proxy}, 账号 {self.account.address} faro 尚未mint，开始mint操作...")

            # 获取账户余额
            balance = await self.w3.eth.get_balance(self.account.address)
            balance_ether = self.w3.from_wei(balance, 'ether')
            # print(f"Current balance: {balance_ether} ETH")
            # 检查余额是否足够支付gas费用和可能的ETH转账
            min_balance_required = self.w3.to_wei(1.02, 'ether')  # 至少需要0.02 ETH
            if balance < min_balance_required:
                logger.warning(
                    f"{self.index}, {self.proxy}, 余额不足，faro NFT 需要至少 1.02 ETH，当前余额: {balance_ether:.6f} ETH")
                return

            temp_data = '##############'.lower()
            # 你提供的inputdata
            # 替换地址（重要：需要重新赋值）
            input_data = input_data.replace(temp_data, str(self.account.address).lower().replace('0x', ''))
            # print(f"替换后的input_data: {input_data[:100]}...")  # 打印前100个字符用于验证

            # 获取当前gas价格
            gas_price = await self.w3.eth.gas_price

            # 估算gas limit
            try:
                # 构建交易用于估算gas
                tx_for_estimate = {
                    'from': self.w3.to_checksum_address(self.account.address),
                    'to': self.w3.to_checksum_address(mint_contract),
                    'data': input_data,
                    'value': self.w3.to_wei(1, 'ether'),  # inputdata中包含1 ETH的值
                }

                estimated_gas = await self.w3.eth.estimate_gas(tx_for_estimate)
                gas_limit = int(estimated_gas * round(random.uniform(1.1, 1.5), 2))  # 增加20%作为缓冲
                # print(f"估算Gas Limit: {gas_limit}")

            except Exception as e:
                # print(f"Gas估算失败:{e}")
                return

            # 构建完整交易
            transaction = {
                'from': self.w3.to_checksum_address(self.account.address),
                'to': self.w3.to_checksum_address(mint_contract),
                'data': input_data,
                'value': self.w3.to_wei(1, 'ether'),  # 从inputdata分析出需要发送1 ETH
                'gas': gas_limit,
                'gasPrice': gas_price,
                'nonce': await self.w3.eth.get_transaction_count(self.w3.to_checksum_address(self.account.address),
                                                                 'pending'),
                'chainId': await self.w3.eth.chain_id
            }

            # print(f"Mint交易详情: to={mint_contract}, value=1 ETH, gas={gas_limit}")

            # 签名交易
            signed_txn = self.account.sign_transaction(transaction)

            # 发送交易
            tx_hash = await self.w3.eth.send_raw_transaction(signed_txn.raw_transaction)
            # print(f"Mint交易已发送，交易哈希: {tx_hash.hex()}")

            # 等待交易确认
            receipt = await self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=300)

            if receipt.status == 1:
                logger.success(f"{self.index}, {self.proxy}, Mint成功！交易哈希: {tx_hash.hex()}")
                # print(f"Gas使用量: {receipt.gasUsed}")
                # print(f"Gas费用: {receipt.gasUsed * gas_price / 10 ** 18:.8f} ETH")

                return tx_hash.hex()
            else:
                logger.error(f"{self.index}, {self.proxy}, faro Mint失败！交易哈希: {tx_hash.hex()}")
                return None

        except Exception as e:
            logger.error(f"{self.index}, {self.proxy}, faro Mint操作出错: {str(e)}")
            import traceback
            traceback.print_exc()
            return None

    async def check_token_balance(self, contract_address=USDC_CONTRACT_ADDRESS):
        balance_abi = [
            {
                "constant": True,
                "inputs": [{"name": "_owner", "type": "address"}],
                "name": "balanceOf",
                "outputs": [{"name": "balance", "type": "uint256"}],
                "type": "function"
            },
            {
                "constant": True,
                "inputs": [],
                "name": "decimals",
                "outputs": [{"name": "", "type": "uint8"}],
                "type": "function"
            }
        ]
        check_contract = self.w3.eth.contract(address=self.w3.to_checksum_address(contract_address), abi=balance_abi)
        balance = await check_contract.functions.balanceOf(self.account.address).call()
        decimals = await check_contract.functions.decimals().call()
        balance_token = balance / (10 ** decimals)
        logger.info(
            f'{self.index}, {self.proxy}, 对应代币合约：{contract_address}, 余额：{balance_token}, decimals:{decimals}')
        return balance_token, decimals

    async def get_pool_price(self, token0=USDT_CONTRACT_ADDRESS, token1=USDC_CONTRACT_ADDRESS,
                             factory_address='0x7CE5b44F2d05babd29caE68557F52ab051265F01'):
        fee = 500  # 0.05% 费用
        # Uniswap V3 Factory ABI（仅包含 getPool）
        factory_abi = [
            {
                "inputs": [
                    {"internalType": "address", "name": "tokenA", "type": "address"},
                    {"internalType": "address", "name": "tokenB", "type": "address"},
                    {"internalType": "uint24", "name": "fee", "type": "uint24"}
                ],
                "name": "getPool",
                "outputs": [{"internalType": "address", "name": "pool", "type": "address"}],
                "stateMutability": "view",
                "type": "function"
            }
        ]
        # Uniswap V3 Pool ABI（仅包含 slot0）
        pool_abi = [
            {
                "inputs": [],
                "name": "slot0",
                "outputs": [
                    {"internalType": "uint160", "name": "sqrtPriceX96", "type": "uint160"},
                    {"internalType": "int24", "name": "tick", "type": "int24"},
                    {"internalType": "uint16", "name": "observationIndex", "type": "uint16"},
                    {"internalType": "uint16", "name": "observationCardinality", "type": "uint16"},
                    {"internalType": "uint16", "name": "observationCardinalityNext", "type": "uint16"},
                    {"internalType": "uint8", "name": "feeProtocol", "type": "uint8"},
                    {"internalType": "bool", "name": "unlocked", "type": "bool"}
                ],
                "stateMutability": "view",
                "type": "function"
            }
        ]
        # 创建 Factory 合约实例
        factory_contract = self.w3.eth.contract(address=self.w3.to_checksum_address(factory_address), abi=factory_abi)

        # 确保 token0 < token1（Uniswap V3 要求地址顺序）
        token_a = token0 if token0.lower() < token1.lower() else token1
        token_b = token1 if token0.lower() < token1.lower() else token0

        # 获取池子地址
        try:
            pool_address = await factory_contract.functions.getPool(
                self.w3.to_checksum_address(token_a),
                self.w3.to_checksum_address(token_b),
                fee
            ).call()
            print(f"池子地址: {pool_address}")
        except Exception as e:
            print(f"获取池子地址失败: {e}")
            return None, None

        # 创建 Pool 合约实例
        pool_contract = self.w3.eth.contract(address=self.w3.to_checksum_address(pool_address), abi=pool_abi)

        # 获取当前价格
        try:
            slot0 = await pool_contract.functions.slot0().call()
            sqrt_price_x96 = slot0[0]
            tick = slot0[1]
            print(f"sqrtPriceX96: {sqrt_price_x96}")
            print(f"当前 Tick: {tick}")
            # 转换为可读价格（价格 = (sqrtPriceX96 / 2^96)^2）
            price = (sqrt_price_x96 / (2 ** 96)) ** 2
            print(f"价格（token1/token0）: {price}")
            return price, sqrt_price_x96, tick
        except Exception as e:
            print(f"获取价格失败: {e}")
            return None, None

    async def mint_pharos_badge_zentra(self):
        mint_contract = '0xe71188df7be6321ffd5aaa6e52e6c96375e62793'
        input_data = "0x84bb1e42000000000000000000000000##############0000000000000000000000000000000000000000000000000000000000000001000000000000000000000000eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee0000000000000000000000000000000000000000000000000de0b6b3a764000000000000000000000000000000000000000000000000000000000000000000c0000000000000000000000000000000000000000000000000000000000000016000000000000000000000000000000000000000000000000000000000000000800000000000000000000000000000000000000000000000000000000000000000ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
        """
        执行mint操作
        """
        try:
            logger.info(f'{self.index}, {self.proxy}, 开始zentra NFT检测')
            # 检查是否已经mint过NFT
            nft_minted = await self.check_nft_balance(contract=mint_contract)
            if nft_minted is True:
                logger.success(
                    f"{self.index}, {self.proxy}, 账号 {self.account.address} 已经拥有zentra NFT，跳过mint操作")
                return "already_minted"

            logger.info(f"{self.index}, {self.proxy}, 账号 {self.account.address} zentra 尚未mint，开始mint操作...")

            # 获取账户余额
            balance = await self.w3.eth.get_balance(self.account.address)
            balance_ether = self.w3.from_wei(balance, 'ether')
            # print(f"Current balance: {balance_ether} ETH")
            # 检查余额是否足够支付gas费用和可能的ETH转账
            min_balance_required = self.w3.to_wei(1.02, 'ether')  # 至少需要0.02 ETH
            if balance < min_balance_required:
                logger.warning(
                    f"{self.index}, {self.proxy}, 余额不足，faro NFT 需要至少 1.02 ETH，当前余额: {balance_ether:.6f} ETH")
                return

            temp_data = '##############'.lower()
            # 你提供的inputdata
            # 替换地址（重要：需要重新赋值）
            input_data = input_data.replace(temp_data, str(self.account.address).lower().replace('0x', ''))
            # print(f"替换后的input_data: {input_data[:100]}...")  # 打印前100个字符用于验证

            # 获取当前gas价格
            gas_price = await self.w3.eth.gas_price

            # 估算gas limit
            try:
                # 构建交易用于估算gas
                tx_for_estimate = {
                    'from': self.w3.to_checksum_address(self.account.address),
                    'to': self.w3.to_checksum_address(mint_contract),
                    'data': input_data,
                    'value': self.w3.to_wei(1, 'ether'),  # inputdata中包含1 ETH的值
                }

                estimated_gas = await self.w3.eth.estimate_gas(tx_for_estimate)
                gas_limit = int(estimated_gas * round(random.uniform(1.1, 1.5), 2))  # 增加20%作为缓冲
                # print(f"估算Gas Limit: {gas_limit}")

            except Exception as e:
                # print(f"Gas估算失败:{e}")
                return

            # 构建完整交易
            transaction = {
                'from': self.w3.to_checksum_address(self.account.address),
                'to': self.w3.to_checksum_address(mint_contract),
                'data': input_data,
                'value': self.w3.to_wei(1, 'ether'),  # 从inputdata分析出需要发送1 ETH
                'gas': gas_limit,
                'gasPrice': gas_price,
                'nonce': await self.w3.eth.get_transaction_count(self.w3.to_checksum_address(self.account.address),
                                                                 'pending'),
                'chainId': await self.w3.eth.chain_id
            }

            print(f"Mint交易详情: to={mint_contract}, value=1 ETH, gas={gas_limit}")

            # 签名交易
            signed_txn = self.account.sign_transaction(transaction)

            # 发送交易
            tx_hash = await self.w3.eth.send_raw_transaction(signed_txn.raw_transaction)
            # print(f"Mint交易已发送，交易哈希: {tx_hash.hex()}")

            # 等待交易确认
            receipt = await self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=300)

            if receipt.status == 1:
                logger.success(f"{self.index}, {self.proxy}, Mint成功！交易哈希: {tx_hash.hex()}")
                # print(f"Gas使用量: {receipt.gasUsed}")
                # print(f"Gas费用: {receipt.gasUsed * gas_price / 10 ** 18:.8f} ETH")

                return tx_hash.hex()
            else:
                logger.error(f"{self.index}, {self.proxy}, faro Mint失败！交易哈希: {tx_hash.hex()}")
                return None

        except Exception as e:
            logger.error(f"{self.index}, {self.proxy}, faro Mint操作出错: {str(e)}")
            import traceback
            traceback.print_exc()
            return None
    async def aquaflux_claim_token(self, aqn_nft_contract_address):
        claim_tokens_abi = [{
            "inputs": [],
            "name": "claimTokens",
            "outputs": [],
            "stateMutability": "nonpayable",
            "type": "function"
        }]
        nft_contract = self.w3.eth.contract(self.w3.to_checksum_address(aqn_nft_contract_address),
                                            abi=claim_tokens_abi)
        est_gas = await nft_contract.functions.claimTokens().estimate_gas({
            'from': self.w3.to_checksum_address(self.account.address)
        })

        # 随机增加 1.01 ~ 1.2 倍缓冲
        multiple_gas = round(random.uniform(1.01, 1.2), 2)
        gas = int(est_gas * multiple_gas)

        # 获取链上 gasPrice、nonce、chainId
        gas_price = await self.w3.eth.gas_price
        nonce = await self.w3.eth.get_transaction_count(
            self.w3.to_checksum_address(self.account.address),
            'pending'
        )
        chain_id = await self.w3.eth.chain_id

        # 构建交易
        tx = await nft_contract.functions.claimTokens().build_transaction({
            "from": self.w3.to_checksum_address(self.account.address),
            "gas": gas,
            "gasPrice": gas_price,
            "nonce": nonce,
            "chainId": chain_id
        })

        # 签名 + 发送
        signed_tx = self.w3.eth.account.sign_transaction(tx, self.account.key)
        tx_hash = await self.w3.eth.send_raw_transaction(signed_tx.raw_transaction)

        # 等待回执
        receipt = await self.w3.eth.wait_for_transaction_receipt(tx_hash)
        if receipt.status == 1:
            logger.success(
                f"{self.index}, {self.proxy}, claim 成功: {self.w3.to_hex(tx_hash)}, block: {receipt.blockNumber}")
            return True


    async def pc_token_claim(self, aqn_nft_contract_address):
        logger.info(f"{self.index}, {self.proxy}, 准备aqua nft mint第二步, pc_token claim")
        input_data = '0x7905642a0000000000000000000000000000000000000000000000056bc75e2d63100000'
        # 获取当前gas价格
        gas_price = await self.w3.eth.gas_price

        # 估算gas limit
        try:
            # 构建交易用于估算gas
            tx_for_estimate = {
                'from': self.w3.to_checksum_address(self.account.address),
                'to': self.w3.to_checksum_address(aqn_nft_contract_address),
                'data': input_data
            }

            estimated_gas = await self.w3.eth.estimate_gas(tx_for_estimate)
            gas_limit = int(estimated_gas * round(random.uniform(1.1, 1.5), 2))  # 增加20%作为缓冲
            # print(f"估算Gas Limit: {gas_limit}")
            # 构建完整交易
            transaction = {
                'from': self.w3.to_checksum_address(self.account.address),
                'to': self.w3.to_checksum_address(aqn_nft_contract_address),
                'data': input_data,
                'gas': gas_limit,
                'gasPrice': gas_price,
                'nonce': await self.w3.eth.get_transaction_count(
                    self.w3.to_checksum_address(self.account.address),
                    'pending'),
                'chainId': await self.w3.eth.chain_id
            }
            # 签名交易
            signed_txn = self.account.sign_transaction(transaction)

            # 发送交易
            tx_hash = await self.w3.eth.send_raw_transaction(signed_txn.raw_transaction)
            # print(f"Mint交易已发送，交易哈希: {tx_hash.hex()}")

            # 等待交易确认
            receipt = await self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=300)

            if receipt.status == 1:
                logger.success(
                    f"{self.index}, {self.proxy}, mint aqua nft第二步成功！交易哈希: {tx_hash.hex()}")
        except Exception as e:
            logger.error(f"{self.index}, {self.proxy}, mint aqua nft第二步失败")

    async def aquaflux_nft_mint(self, aquaflux_headers, aqn_nft_contract_address):
        res = await self.session.post(url='https://api.aquaflux.pro/api/v1/users/check-token-holding',
                                      headers=aquaflux_headers)
        logger.info(f'{self.index}, {self.proxy}, token-holding check结果:{res.text}')
        if res.status_code == 200:
            if res.json()['data']['isHoldingToken']:
                signature_url = 'https://api.aquaflux.pro/api/v1/users/get-signature'
                payload = {"walletAddress": self.account.address, "requestedNftType": 0}
                res = await self.session.post(url=signature_url, headers=aquaflux_headers,
                                              json=payload)
                logger.info(f'{self.index}, {self.proxy}, signature获取结果:{res.text}')
                if res.status_code == 200:
                    signature = str(res.json()['data']['signature']).removeprefix('0x')
                    expires_at = res.json()['data']['expiresAt']
                    input_data = '0x75e7e0530000000000000000000000000000000000000000000000000000000000000000%%%%%%%%%%%00000000000000000000000000000000000000000000000000000000000000600000000000000000000000000000000000000000000000000000000000000041###########00000000000000000000000000000000000000000000000000000000000000'
                    timestamp_encoded = encode_uint256(expires_at)
                    temp_timestamp_old = '%%%%%%%%%%%'
                    temp_signature_old = '###########'
                    input_data = input_data.replace(temp_timestamp_old, timestamp_encoded)
                    input_data = input_data.replace(temp_signature_old, signature)
                    logger.info(f'{self.index}, {self.proxy}, 当前nft mint的input_data={input_data}')
                    gas_price = await self.w3.eth.gas_price

                    # 构建交易用于估算gas
                    tx_for_estimate = {
                        'from': self.w3.to_checksum_address(self.account.address),
                        'to': self.w3.to_checksum_address(aqn_nft_contract_address),
                        'data': input_data
                    }
                    estimated_gas = await self.w3.eth.estimate_gas(tx_for_estimate)

                    gas_limit = int(estimated_gas * round(random.uniform(1.1, 1.5), 2))  # 增加20%作为缓冲

                    transaction = {
                        'from': self.w3.to_checksum_address(self.account.address),
                        'to': self.w3.to_checksum_address(aqn_nft_contract_address),
                        'data': input_data,
                        'gas': gas_limit,
                        'gasPrice': gas_price,
                        'nonce': await self.w3.eth.get_transaction_count(
                            self.w3.to_checksum_address(self.account.address),
                            'pending'),
                        'chainId': await self.w3.eth.chain_id
                    }

                    # 签名交易
                    signed_txn = self.account.sign_transaction(transaction)

                    # 发送交易
                    tx_hash = await self.w3.eth.send_raw_transaction(signed_txn.raw_transaction)
                    # print(f"Mint交易已发送，交易哈希: {tx_hash.hex()}")

                    # 等待交易确认
                    receipt = await self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=300)

                    if receipt.status == 1:
                        logger.success(
                            f"{self.index}, {self.proxy}, mint aqua nft最终交易成功！交易哈希: {tx_hash.hex()}")
                        return True

    async def rwa_fi(self):

        P_TOKEN_ADDRESS = '0xb5d3ca5802453cc06199b9c40c855a874946a92c'
        aqn_nft_contract_address = '0xcc8cf44e196cab28dba2d514dc7353af0efb370e'
        PC_TOKEN_ADDRESS = '0x37eca06be40cd4ebf225bed4a99dd3491ace0044'
        # 校验NFT是否已经mint
        nft_minted = await self.check_nft_balance(aqn_nft_contract_address)
        if nft_minted:
            logger.success(f'{self.index}, {self.proxy}, aquaflux nft已经mint！')
            return
        # 登录aquaflux
        t = int(time.time() * 1000)
        message = f'Sign in to AquaFlux with timestamp: {t}'
        aquaflux_headers = {
            "accept": "application/json, text/plain, */*",
            "accept-encoding": "gzip, deflate, br, zstd",
            "accept-language": "zh-CN,zh;q=0.8",
            "origin": "https://playground.aquaflux.pro",
            "priority": "u=1, i",
            "referer": "https://playground.aquaflux.pro/",
            "sec-ch-ua-mobile": "?0",
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-site",
            "sec-gpc": "1"
        }
        signature = '0x' + self.account.sign_message(encode_defunct(text=message)).signature.hex()

        payload = {
            "address": self.account.address,
            "message": message,
            "signature": signature
        }
        login_url = 'https://api.aquaflux.pro/api/v1/users/wallet-login'
        res = await self.session.post(login_url, json=payload, headers=aquaflux_headers)
        if 'Authentication token not provided' in res.text:
            return
        if res.status_code == 200:
            logger.success(f"{self.index}, {self.proxy}, aquax登录成功!")
            access_token = res.json()['data']['accessToken']
            aquaflux_headers.update({
                'authorization': f'Bearer {access_token}'
            })
            binding_status_url = 'https://api.aquaflux.pro/api/v1/users/twitter/binding-status'
            await self.session.get(binding_status_url, headers=aquaflux_headers)
            await asyncio.sleep(1)
            await self.session.get(binding_status_url, headers=aquaflux_headers)

        # 如果p_token, pc_token均为0 则进行claim
        p_token_balance, p_token_wei = await self.check_token_balance(P_TOKEN_ADDRESS)
        pc_token_balance, pc_token_wei = await self.check_token_balance(PC_TOKEN_ADDRESS)
        if float(pc_token_balance) == 0.0 and float(p_token_balance) == 0.0:
            logger.info(
                f'{self.index}, {self.proxy}, aquaflux nft尚未mint, 且pc_token, p_token均为0，进行p_token进行claim')
            await self.aquaflux_claim_token(aqn_nft_contract_address)
            for i in range(99):
                p_token_balance, p_token_wei = await self.check_token_balance(P_TOKEN_ADDRESS)
                if float(p_token_balance) == 0.0:
                    await asyncio.sleep(random.uniform(5.8, 11.5))
                    continue
                else:
                    await self.pc_token_claim(aqn_nft_contract_address)
                    await asyncio.sleep(random.uniform(5.8, 11.5))
                    break
        # 如果
        pc_token_flag = False
        for i in range(99):
            pc_token_balance, pc_token_wei = await self.check_token_balance(PC_TOKEN_ADDRESS)
            if float(pc_token_balance) == 0.0:
                logger.info(f'{self.index}, {self.proxy}, pc_token为0, 准备claim pc token')
                await asyncio.sleep(random.uniform(5.8, 11.5))
                p_token_balance, p_token_wei = await self.check_token_balance(P_TOKEN_ADDRESS)
                # todo check-point
                if float(p_token_balance) == 0.0:
                    await self.pc_token_claim(aqn_nft_contract_address)
                    await asyncio.sleep(random.uniform(5.8, 11.5))
                    continue
            else:
                logger.info(f'{self.index}, {self.proxy}, pc_token不为0, 退出，准备nft的mint')
                pc_token_flag = True
                break
        if pc_token_flag:
            for i in range(99):
                pc_token_balance, pc_token_wei = await self.check_token_balance(PC_TOKEN_ADDRESS)
                if float(pc_token_balance) > 0.0:
                    logger.info(f'{self.index}, {self.proxy}, pc_token 不为0, 准备nft 的mint')
                    nft_mint_flag = await self.aquaflux_nft_mint(aquaflux_headers, aqn_nft_contract_address)
                    await asyncio.sleep(random.uniform(5.8, 11.5))
                    if nft_mint_flag:
                        if await self.check_nft_balance(aqn_nft_contract_address):
                            logger.success(f'{self.index}, {self.proxy}, aquaflux nft mint 已成功!')
                            await asyncio.sleep(random.uniform(5.8, 11.5))
                            return
                else:
                    if await self.check_nft_balance(aqn_nft_contract_address):
                        logger.success(f'{self.index}, {self.proxy}, aquaflux nft mint 已成功!')
                        return
                    else:
                        await asyncio.sleep(random.uniform(5.8, 11.5))

    async def auto(self):
        """
        自动执行所有任务
        """
        try:
            logger.info(f"{self.index}, {self.proxy}, Starting tasks for account: {self.account.address}")
            print(self.proxy)

            await self.login()
            await self.interaction_statistic()
            logger.info(f"{self.index}, {self.proxy}, 当前账号情况：send_times:{self.send_times},\n"
                        f"zeith_swap: {self.zeith_swap_times}, \n"
                        f"zeith_liq: {self.zeith_liq_times}\n"
                        f"faros_swap: {self.faros_swap_times}\n"
                        f"faros_liq: {self.faros_liq_times}")

            if self.ilsh['mint_nft']:
                await self.mint()
                await self.mint_pharos_badge2()
                await self.mint_pharos_badge_zentra()

            if self.ilsh['rwa_fi']:
                await self.rwa_fi()
            # # await self.mint_faro_badge()
            # #
            await self.profile()
            await self.tasks()
            if self.ilsh['daily_check']:
                await self.check_in()

            await self.do_task()
            # # # #
            # await self.faucet_usdc_usdt()
            if self.x_id is not None and len(self.x_id) > 5:
                if self.ilsh['faucet_phrs']:
                    await self.faucet_PHRS()
            # #
            await self.check_account_status()
            interact_max = 91
            self.interact_max = interact_max
            if self.onchain_enable:

                # 执行代币自转
                if self.send_times < interact_max:
                    if self.ilsh['send_to_friends']:
                        await self.transfer()
                if self.faros_swap_times < interact_max:
                    if self.ilsh['faroswap']:
                        await self.faros_swap()
                if self.zeith_liq_times < interact_max:
                    if self.ilsh['zenith_liq']:
                        await self.add_liq()
            #
            print(f"Completed all tasks for account: {self.account.address}")

        except Exception as e:
            print(f"Error for account {self.account.address}: {str(e)}")
        finally:
            pass


async def run(acc: dict, all_data: dict):
    """运行单个账号的任务"""
    try:
        mnemonic = acc['mnemonic']
        proxy = acc['proxy']
        invite = acc.get('invite', '')  # 使用默认空邀请码如果没有提供
        index = acc.get('index')
        ilsh_config = acc.get('ilsh')

        headers = {
            "accept": "application/json, text/plain, */*",
            "accept-encoding": "gzip, deflate, br, zstd",
            "accept-language": "zh-CN,zh;q=0.9",
            "origin": "https://testnet.pharosnetwork.xyz",
            "priority": "u=1, i",
            "referer": "https://testnet.pharosnetwork.xyz/",
        }

        pharos = Pharos(mnemonic, proxy, invite, headers, index, ilsh_config)
        pharos.all_data = all_data
        await pharos.init_web3()
        await pharos.auto()
    except Exception as e:
        print(f"Error in run: {str(e)}")


async def batch_run(accounts, batch_size: int, delay_between_batches: int):
    """
    分批次运行账号，使用更自然的时间间隔

    Args:
        accounts: 账号列表
        batch_size: 每批次账号数量
        delay_between_batches: 批次之间的基础延迟(秒)
    """
    all_data = {}
    for i in range(0, len(accounts), batch_size):
        actual_batch_size = batch_size
        batch = accounts[i:i + actual_batch_size]
        print(f"开始执行第 {i // batch_size + 1} 批账号，数量: {len(batch)}")

        # 不是所有任务同时启动，而是有间隔地启动
        tasks = [run(acc, all_data) for acc in batch]
        await asyncio.gather(*tasks)

        if i + actual_batch_size < len(accounts):  # 如果不是最后一批，则等待
            # 批次之间的等待时间带有随机性
            actual_delay = delay_between_batches * random.uniform(0.8, 1.2)
            print(f"当前批次完成，等待 {actual_delay:.1f} 秒后执行下一批...")
            await asyncio.sleep(actual_delay)


async def get_proxy_from_smartproxies(smart_proxies_url) -> []:
    async with httpx.AsyncClient() as client:
        res = await client.get(smart_proxies_url)
        # 1. 从JSON数据中获取原始的代理列表
        original_proxy_list = res.json().get('data', {}).get('list', [])

        # 2. 使用列表推导式为每个代理添加前缀
        formatted_proxy_list = [f"http://{proxy}" for proxy in original_proxy_list]

        # 3. 返回格式化后的新列表
        return formatted_proxy_list
def get_account_proxy(index:int, proxies:list):
    if index < len(proxies) - 1:
        proxy = proxies[index]
        print(proxy)
        return proxy
    else:
        return random.choice(proxies)

async def main_once(ilsh_config: dict):
    accs = []
    invites = []
    proxies = []
    with open('./invite_codes.txt', 'r') as file:
        for line in file.readlines():
            code = line.strip()
            invites.append(code)
    with open('./native_proxies.txt', 'r') as file:
        for line in file.readlines():
            proxy = line.strip()
            proxies.append(proxy)


    with open('acc.txt', 'r') as f:
        for index, line in enumerate(f.readlines()):
            line = line.strip()
            if not line or line.startswith('#'):
                continue

            mnemonic = line.strip()
            if mnemonic:
                invite = random.choice(invites)

                accs.append({
                    'mnemonic': mnemonic,
                    'invite': invite,
                    'proxy': get_account_proxy(index, proxies),
                    'index': index,
                    'ilsh': ilsh_config
                })
            else:
                print(f"Invalid line format: {line}")

    # 随机化账号顺序
    random.shuffle(accs)
    logger.info(f"总账号数: {len(accs)}")

    # 设置批次参数
    base_batch_size = ilsh_config['batch_size']  # 批次大小
    base_delay = random.randint(5, 10)  # 批次间延迟(秒)

    logger.info(f'准备批量处理，批次大小约{base_batch_size}，批次间隔约{base_delay / 60:.1f}分钟')

    # 开始前的准备时间
    # 开始前的准备时间
    startup_delay = 0
    logger.info(f"准备开始，{startup_delay:.1f}秒后开始处理...")
    await asyncio.sleep(startup_delay)

    # 使用批处理运行
    await batch_run(accs, base_batch_size, base_delay)


async def main(ilsh_config: dict):
    i = 1
    while True:
        logger.info(f"==== 第{i}轮批量处理开始 ====")
        await main_once(ilsh_config)
        logger.info(f"==== 第{i}轮批量处理结束 ====")
        # 睡眠x小时（如6小时=21600秒），可加随机性
        sleep_time = 3600 * ilsh_config['round_delay'] * random.uniform(0.85, 1.15)  # 6小时±15%
        logger.info(f"休息 {sleep_time / 3600:.2f} 小时后再运行下一轮...\n")
        await asyncio.sleep(sleep_time)
        i += 1


def read_config():
    with open('./ilshauto.config', 'r') as file:
        config = json.load(file)
    return config


if __name__ == '__main__':

    print('@正在读取配置信息')
    ilsh_config = read_config()
    print(f'@当前配置信息：{ilsh_config}')

    logger.debug('🚀 [ILSH] Pharos v1.0 | Airdrop Campaign Live')
    logger.debug('🌐 ILSH Community 电报频道: t.me/ilsh_auto')
    logger.debug('🐦 X(Twitter) 推特: https://x.com/hashlmBrian')
    logger.debug('☕ Pay me Coffe USDT（TRC20）:TAiGnbo2isJYvPmNuJ4t5kAyvZPvAmBLch')
    asyncio.run(main(ilsh_config))