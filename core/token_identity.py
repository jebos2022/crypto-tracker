from dataclasses import dataclass


PRICING_DIRECT = "direct"
PRICING_EQUIVALENT = "equivalent"
PRICING_STAKE_EVENT = "stake_event"


@dataclass(frozen=True)
class TokenIdentity:
    chain: str
    contract_address: str | None
    canonical_asset: str
    coingecko_id: str
    pricing_policy: str = PRICING_DIRECT


@dataclass(frozen=True)
class StakingWrapper:
    chain: str
    wrapper_asset: str
    wrapper_contract: str
    underlying_asset: str
    underlying_contract: str
    staking_contract: str
    underlying_coingecko_id: str
    pricing_policy: str = PRICING_STAKE_EVENT
    notes: str = ""


WETH_CONTRACTS: dict[str, str] = {
    "ethereum": "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2",
    "arbitrum": "0x82af49447d8a07e3bd95bd0d56f35241523fbab1",
    "base": "0x4200000000000000000000000000000000000006",
    "optimism": "0x4200000000000000000000000000000000000006",
    "polygon": "0x7ceb23fd6bc0add59e62ac25578270cff1b9f619",
}

USDC_CONTRACTS: dict[str, str] = {
    "ethereum": "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48",
    "arbitrum": "0xaf88d065e77c8cc2239327c5edb3a432268e5831",
    "base": "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",
    "optimism": "0x0b2c639c533813f4aa9d7837caf62653d097ff85",
    "polygon": "0x3c499c542cef5e3811e1192ce70d8cc03d5c3359",
}

USDT_CONTRACTS: dict[str, str] = {
    "ethereum": "0xdac17f958d2ee523a2206206994597c13d831ec7",
    "arbitrum": "0xfd086bc7cd5c481dcc9c85ebe478a1c0b69fcbb9",
    "optimism": "0x94b008aa00579c1307b0ef2c499ad98a8ce58e58",
    "polygon": "0xc2132d05d31c914a87c6611c10748aeb04b58e8f",
}

DAI_CONTRACTS: dict[str, str] = {
    "ethereum": "0x6b175474e89094c44da98b954eedeac495271d0f",
    "arbitrum": "0xda10009cbd5d07dd0cecc66161fc93d7c9000da1",
    "optimism": "0xda10009cbd5d07dd0cecc66161fc93d7c9000da1",
    "polygon": "0x8f3cf7ad23cd3cadbd9735aff958023239c6a063",
}

WBTC_CONTRACTS: dict[str, str] = {
    "ethereum": "0x2260fac5e5542a773aa44fbcfedf7c193bc2c599",
    "arbitrum": "0x2f2a2543b76a4166549f7aab2e75bef0aefc5b0f",
    "optimism": "0x68f180fcce6836688e9084f035309e29bf0a2095",
    "polygon": "0x1bfd67037b42cf73acf2047067bd4f2c47d9bfd6",
}

ARB_ARBITRUM_CONTRACT = "0x912ce59144191c1204e64559fe8253a0e49e6548"
BEAM_ERC20_CONTRACT = "0x62d0a8458ed7719fdaf978fe5929c6d342b0bfce"
WBEAM_BEAM_CONTRACT = "0xd51bfa777609213a653a2cd067c9a0132a2d316a"
ATH_ETHEREUM_CONTRACT = "0xbe0ed4138121ecfc5c0e56b40517da27e6c5226b"
ATH_ARBITRUM_CONTRACT = "0xc87b37a581ec3257b734886d9d3a581f5a9d056c"

STAKING_WRAPPERS: tuple[StakingWrapper, ...] = (
    StakingWrapper(
        chain="ethereum",
        wrapper_asset="xOPN",
        wrapper_contract="0x686e8500b6be8812eb198aabbbfa14c95c03fc88",
        underlying_asset="OPN",
        underlying_contract="0xc28eb2250d1ae32c7e74cfb6d6b86afc9beb6509",
        staking_contract="0x686e8500b6be8812eb198aabbbfa14c95c03fc88",
        underlying_coingecko_id="open-ticketing-ecosystem",
        notes="Use the OPN amount sent to staking for stake value; recognize yield on unstake.",
    ),
    StakingWrapper(
        chain="arbitrum",
        wrapper_asset="stPEAR",
        wrapper_contract="0xce3be5204017bb1bd279937f92df09fd7f539b92",
        underlying_asset="PEAR",
        underlying_contract="0x3212dc0f8c834e4de893532d27cc9b6001684db0",
        staking_contract="0xce3be5204017bb1bd279937f92df09fd7f539b92",
        underlying_coingecko_id="pear-protocol",
        notes="Use the PEAR amount sent to staking for stake value; recognize yield on unstake.",
    ),
)

STAKED_TOKENS: dict[str, dict[str, dict]] = {}
for _wrapper in STAKING_WRAPPERS:
    STAKED_TOKENS.setdefault(_wrapper.chain, {})[_wrapper.wrapper_asset] = {
        "underlying": _wrapper.underlying_asset,
        "underlying_contract": _wrapper.underlying_contract,
        "staking_contract": _wrapper.staking_contract,
        "wrapper_contract": _wrapper.wrapper_contract,
        "pricing_policy": _wrapper.pricing_policy,
        "underlying_coingecko_id": _wrapper.underlying_coingecko_id,
        "notes": _wrapper.notes,
    }


def _normalized_contract(contract_address: str | None) -> str | None:
    contract = (contract_address or "").strip().lower()
    return contract or None


def _identity(
    chain: str,
    contract_address: str | None,
    canonical_asset: str,
    coingecko_id: str,
    pricing_policy: str = PRICING_DIRECT,
) -> TokenIdentity:
    return TokenIdentity(
        chain=chain,
        contract_address=_normalized_contract(contract_address),
        canonical_asset=canonical_asset,
        coingecko_id=coingecko_id,
        pricing_policy=pricing_policy,
    )


TOKEN_IDENTITIES: dict[tuple[str, str | None], TokenIdentity] = {
    ("ethereum", None): _identity("ethereum", None, "ETH", "ethereum"),
    ("arbitrum", None): _identity("arbitrum", None, "ETH", "ethereum"),
    ("base", None): _identity("base", None, "ETH", "ethereum"),
    ("optimism", None): _identity("optimism", None, "ETH", "ethereum"),
    ("polygon", None): _identity("polygon", None, "POL", "polygon-ecosystem-token"),
    ("beam", None): _identity("beam", None, "BEAM", "beam-2"),
    ("arbitrum", ARB_ARBITRUM_CONTRACT): _identity(
        "arbitrum", ARB_ARBITRUM_CONTRACT, "ARB", "arbitrum"
    ),
    ("ethereum", BEAM_ERC20_CONTRACT): _identity(
        "ethereum", BEAM_ERC20_CONTRACT, "BEAM", "beam-2", PRICING_EQUIVALENT
    ),
    ("beam", WBEAM_BEAM_CONTRACT): _identity(
        "beam", WBEAM_BEAM_CONTRACT, "BEAM", "beam-2", PRICING_EQUIVALENT
    ),
    ("ethereum", ATH_ETHEREUM_CONTRACT): _identity(
        "ethereum", ATH_ETHEREUM_CONTRACT, "ATH", "aethir"
    ),
    ("arbitrum", ATH_ARBITRUM_CONTRACT): _identity(
        "arbitrum", ATH_ARBITRUM_CONTRACT, "ATH", "aethir"
    ),
}
TOKEN_IDENTITIES.update(
    {
        (chain, contract.lower()): _identity(chain, contract, "WETH", "weth")
        for chain, contract in WETH_CONTRACTS.items()
    }
)
TOKEN_IDENTITIES.update(
    {
        (chain, contract.lower()): _identity(chain, contract, "USDC", "usd-coin")
        for chain, contract in USDC_CONTRACTS.items()
    }
)
TOKEN_IDENTITIES.update(
    {
        (wrapper.chain, wrapper.underlying_contract.lower()): _identity(
            wrapper.chain,
            wrapper.underlying_contract,
            wrapper.underlying_asset,
            wrapper.underlying_coingecko_id,
        )
        for wrapper in STAKING_WRAPPERS
    }
)
TOKEN_IDENTITIES.update(
    {
        (wrapper.chain, wrapper.wrapper_contract.lower()): _identity(
            wrapper.chain,
            wrapper.wrapper_contract,
            wrapper.underlying_asset,
            wrapper.underlying_coingecko_id,
            PRICING_STAKE_EVENT,
        )
        for wrapper in STAKING_WRAPPERS
    }
)

COINGECKO_IDS: dict[tuple[str, str | None], str] = {
    key: identity.coingecko_id
    for key, identity in TOKEN_IDENTITIES.items()
    if identity.pricing_policy != PRICING_STAKE_EVENT
}


def _native_symbol_for(chain: str) -> str | None:
    identity = TOKEN_IDENTITIES.get((chain, None))
    return identity.canonical_asset if identity else None


def token_identity_for(
    chain: str,
    contract_address: str | None,
    asset: str | None = None,
) -> TokenIdentity | None:
    contract = _normalized_contract(contract_address)
    if contract:
        return TOKEN_IDENTITIES.get((chain, contract))

    asset_symbol = (asset or "").strip()
    wrapper = staking_wrapper_for(chain, asset=asset_symbol)
    if wrapper:
        return TOKEN_IDENTITIES.get((chain, wrapper.wrapper_contract.lower()))

    native_symbol = _native_symbol_for(chain)
    if asset_symbol and native_symbol and asset_symbol.upper() != native_symbol.upper():
        return None
    return TOKEN_IDENTITIES.get((chain, None))


def coingecko_id_for(
    chain: str,
    contract_address: str | None,
    asset: str | None = None,
) -> str | None:
    identity = token_identity_for(chain, contract_address, asset)
    if not identity:
        return None
    if identity.pricing_policy == PRICING_STAKE_EVENT:
        return None
    return identity.coingecko_id


def canonical_asset_for(
    chain: str,
    contract_address: str | None,
    asset: str | None = None,
) -> str | None:
    identity = token_identity_for(chain, contract_address, asset)
    return identity.canonical_asset if identity else None


def staking_wrapper_for(
    chain: str,
    contract_address: str | None = None,
    asset: str | None = None,
) -> StakingWrapper | None:
    contract = _normalized_contract(contract_address)
    asset_symbol = (asset or "").strip()
    for wrapper in STAKING_WRAPPERS:
        if wrapper.chain != chain:
            continue
        if contract and contract == wrapper.wrapper_contract.lower():
            return wrapper
        if asset_symbol and asset_symbol == wrapper.wrapper_asset:
            return wrapper
    return None


def get_staked_info(chain: str, asset: str) -> dict | None:
    return STAKED_TOKENS.get(chain, {}).get(asset)


def is_staking_wrapper_contract(chain: str, contract_address: str | None) -> bool:
    identity = token_identity_for(chain, contract_address)
    return bool(identity and identity.pricing_policy == PRICING_STAKE_EVENT)


def identity_contracts_by_asset() -> dict[str, dict[str, set[str]]]:
    result: dict[str, dict[str, set[str]]] = {}
    for (chain, contract), identity in TOKEN_IDENTITIES.items():
        if contract is None:
            continue
        result.setdefault(identity.canonical_asset, {}).setdefault(chain, set()).add(contract)
    for wrapper in STAKING_WRAPPERS:
        result.setdefault(wrapper.wrapper_asset, {}).setdefault(wrapper.chain, set()).add(
            wrapper.wrapper_contract.lower()
        )
    return result


def is_known_safe_token_contract(chain: str, contract_address: str | None) -> bool:
    contract = _normalized_contract(contract_address)
    if not contract:
        return False
    return (chain, contract) in TOKEN_IDENTITIES or is_staking_wrapper_contract(chain, contract)
