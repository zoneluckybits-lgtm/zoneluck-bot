import httpx
from utils import get_setting

USDT_TRC20_CONTRACT = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"
USDT_BEP20_CONTRACT = "0x55d398326f99059fF775485246999027B3197955"


async def verify_trc20(tx_hash: str, expected_to: str) -> dict:
    """
    Verify a USDT TRC-20 transaction via Tronscan public API.
    Returns: {ok, amount, to_address, confirmed, error}
    """
    url = f"https://apilist.tronscanapi.com/api/transaction-info?hash={tx_hash}"
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        return {"ok": False, "error": f"تعذّر الاتصال بـ Tronscan: {e}"}

    if data.get("contractRet") == "REVERT" or not data.get("contractData"):
        return {"ok": False, "error": "العملية غير موجودة أو فشلت على الشبكة."}

    confirmed = data.get("confirmed", False)
    contract_data = data.get("contractData", {})
    token_info = contract_data.get("token_info", {})

    token_address = token_info.get("tokenId", "").lower()
    if token_address != USDT_TRC20_CONTRACT.lower():
        return {"ok": False, "error": "هذه العملية ليست USDT TRC-20."}

    to_address = contract_data.get("to_address", "")
    amount_raw = contract_data.get("amount", 0)
    decimals = int(token_info.get("tokenDecimal", 6))
    amount = amount_raw / (10 ** decimals)

    expected_clean = expected_to.strip().upper() if expected_to else ""
    actual_clean = to_address.strip().upper() if to_address else ""

    if expected_clean and actual_clean != expected_clean:
        return {
            "ok": False,
            "error": f"العملية لم تصل لمحفظة البوت.\nالمحفظة المستلِمة: `{to_address}`"
        }

    return {
        "ok": True,
        "amount": round(amount, 2),
        "to_address": to_address,
        "confirmed": confirmed,
        "error": None,
    }


async def verify_bep20(tx_hash: str, expected_to: str) -> dict:
    """
    Verify a USDT BEP-20 transaction via BSCScan public API (no key needed for basic use).
    Returns: {ok, amount, to_address, confirmed, error}
    """
    url = (
        "https://api.bscscan.com/api"
        "?module=proxy&action=eth_getTransactionByHash"
        f"&txhash={tx_hash}"
        "&apikey=YourApiKeyToken"
    )
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        return {"ok": False, "error": f"تعذّر الاتصال بـ BSCScan: {e}"}

    tx = data.get("result")
    if not tx or tx == "Transaction not found":
        return {"ok": False, "error": "العملية غير موجودة على شبكة BSC."}

    to_address = (tx.get("to") or "").lower()

    if to_address != USDT_BEP20_CONTRACT.lower():
        return {"ok": False, "error": "هذه العملية ليست USDT BEP-20 (عنوان العقد غير مطابق)."}

    input_data = tx.get("input", "")
    amount = 0.0
    recipient = ""

    if len(input_data) >= 138 and input_data.startswith("0xa9059cbb"):
        recipient_hex = input_data[10:74]
        amount_hex = input_data[74:138]
        try:
            recipient = "0x" + recipient_hex[-40:]
            amount = int(amount_hex, 16) / 1e18
        except Exception:
            pass

    expected_clean = expected_to.strip().lower() if expected_to else ""
    if expected_clean and recipient.lower() != expected_clean:
        return {
            "ok": False,
            "error": f"العملية لم تصل لمحفظة البوت.\nالمحفظة المستلِمة: `{recipient}`"
        }

    block_number = tx.get("blockNumber")
    confirmed = block_number is not None and block_number != "0x0"

    return {
        "ok": True,
        "amount": round(amount, 2),
        "to_address": recipient,
        "confirmed": confirmed,
        "error": None,
    }


async def verify_tx(network: str, tx_hash: str) -> dict:
    """
    Auto-detect network and verify. network: 'TRC-20' or 'BEP-20'
    Reads wallet address from DB settings automatically.
    """
    if network == "TRC-20":
        wallet = get_setting("trc20_address") or ""
        return await verify_trc20(tx_hash, wallet)
    elif network == "BEP-20":
        wallet = get_setting("bep20_address") or ""
        return await verify_bep20(tx_hash, wallet)
    else:
        return {"ok": False, "error": "شبكة غير معروفة."}
