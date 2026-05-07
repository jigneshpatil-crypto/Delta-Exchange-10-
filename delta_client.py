"""
Heikin-Ashi + Chandelier Exit + LSMA Filter — Delta Exchange India API Client
Direct REST API wrapper with HMAC-SHA256 authentication.
Supports both Testnet and Production environments.
"""

import hashlib
import hmac
import json
import time
import logging
import requests

import config

logger = logging.getLogger("DeltaClient")


class DeltaClient:
    """Delta Exchange India REST API v2 client."""

    def __init__(self):
        self.base_url = config.DELTA_BASE_URL.rstrip("/")
        self.api_key = config.DELTA_API_KEY
        self.api_secret = config.DELTA_API_SECRET
        self.session = requests.Session()
        if hasattr(config, 'PROXY_URL') and config.PROXY_URL:
            self.session.proxies = {
                "http": config.PROXY_URL,
                "https": config.PROXY_URL,
            }
        self.session.headers.update({
            "Content-Type": "application/json",
            "User-Agent": "ha-ce-lsma-bot",
        })
        self._product_id_cache = {}

    # ---------------------------------------------------------------
    # Authentication
    # ---------------------------------------------------------------
    def _generate_signature(self, method, path, query_string="", payload=""):
        """Generate HMAC-SHA256 signature for Delta Exchange API."""
        timestamp = str(int(time.time()))
        message = method + timestamp + path + query_string + payload
        signature = hmac.new(
            bytes(self.api_secret, "utf-8"),
            bytes(message, "utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return timestamp, signature

    def _auth_headers(self, method, path, query_string="", payload=""):
        """Build authenticated request headers."""
        timestamp, signature = self._generate_signature(
            method, path, query_string, payload
        )
        return {
            "api-key": self.api_key,
            "timestamp": timestamp,
            "signature": signature,
        }

    # ---------------------------------------------------------------
    # Core Request Methods
    # ---------------------------------------------------------------
    def _get(self, path, params=None, auth=False):
        """Send GET request."""
        url = f"{self.base_url}{path}"
        query_string = ""
        if params:
            query_string = "?" + "&".join(f"{k}={v}" for k, v in params.items())

        headers = {}
        if auth:
            if not self.api_key or not self.api_secret:
                logger.error("CRITICAL: API Key or Secret is EMPTY. Check Render Environment Variables!")
                return None
            headers = self._auth_headers("GET", path, query_string)

        try:
            resp = self.session.get(
                url, params=params, headers=headers, timeout=(5, 30)
            )
            if resp.status_code != 200:
                logger.error(f"API HTTP {resp.status_code} Error on GET {path}: {resp.text}")
                return None
                
            data = resp.json()
            if not data.get("success", True):
                error = data.get("error", {})
                logger.error(f"Delta API Logic Error on GET {path}: {error}")
                return None
            return data.get("result", data)
        except Exception as e:
            logger.error(f"Network/Request failed GET {path}: {str(e)}")
            return None

    def _post(self, path, payload_dict):
        """Send authenticated POST request."""
        url = f"{self.base_url}{path}"
        payload = json.dumps(payload_dict, separators=(",", ":"))

        headers = self._auth_headers("POST", path, "", payload)

        try:
            resp = self.session.post(
                url, data=payload, headers=headers, timeout=(5, 30)
            )
            resp.raise_for_status()
            data = resp.json()
            if not data.get("success", True):
                error = data.get("error", {})
                logger.error(f"API Error on POST {path}: {error}")
                return None
            return data.get("result", data)
        except requests.exceptions.RequestException as e:
            logger.error(f"Request failed POST {path}: {e}")
            return None

    def _put(self, path, payload_dict):
        """Send authenticated PUT request."""
        url = f"{self.base_url}{path}"
        payload = json.dumps(payload_dict, separators=(",", ":"))

        headers = self._auth_headers("PUT", path, "", payload)

        try:
            resp = self.session.put(
                url, data=payload, headers=headers, timeout=(5, 30)
            )
            resp.raise_for_status()
            data = resp.json()
            if not data.get("success", True):
                error = data.get("error", {})
                logger.error(f"API Error on PUT {path}: {error}")
                return None
            return data.get("result", data)
        except requests.exceptions.RequestException as e:
            logger.error(f"Request failed PUT {path}: {e}")
            return None

    def _delete(self, path, payload_dict=None):
        """Send authenticated DELETE request."""
        url = f"{self.base_url}{path}"
        payload = ""
        if payload_dict:
            payload = json.dumps(payload_dict, separators=(",", ":"))

        headers = self._auth_headers("DELETE", path, "", payload)

        try:
            resp = self.session.delete(
                url, data=payload if payload else None,
                headers=headers, timeout=(5, 30)
            )
            resp.raise_for_status()
            data = resp.json()
            if not data.get("success", True):
                error = data.get("error", {})
                logger.error(f"API Error on DELETE {path}: {error}")
                return None
            return data.get("result", data)
        except requests.exceptions.RequestException as e:
            logger.error(f"Request failed DELETE {path}: {e}")
            return None

    # ---------------------------------------------------------------
    # Product Discovery
    # ---------------------------------------------------------------
    def get_product_id(self, symbol=None):
        """Get product_id for a symbol. Caches result."""
        symbol = symbol or config.SYMBOL
        if symbol in self._product_id_cache:
            return self._product_id_cache[symbol]

        result = self._get(f"/v2/products/{symbol}")
        if result:
            product_id = result.get("id")
            self._product_id_cache[symbol] = product_id
            logger.info(f"Product {symbol} → ID: {product_id}")
            return product_id

        # Fallback: search in products list
        products = self._get("/v2/products", params={"page_size": 100})
        if products:
            for p in products:
                if p.get("symbol") == symbol:
                    product_id = p["id"]
                    self._product_id_cache[symbol] = product_id
                    logger.info(f"Product {symbol} → ID: {product_id}")
                    return product_id

        logger.error(f"Could not find product_id for {symbol}")
        return None

    def get_product_info(self, symbol=None):
        """Get full product details including tick_size, min_size etc."""
        symbol = symbol or config.SYMBOL
        result = self._get(f"/v2/products/{symbol}")
        return result

    # ---------------------------------------------------------------
    # Market Data (Public — No Auth)
    # ---------------------------------------------------------------
    def get_candles(self, symbol=None, resolution=None, start=None, end=None, limit=None):
        """
        Fetch OHLCV candles.
        GET /v2/history/candles
        Delta API requires 'start' and 'end' timestamps.
        If not provided, we auto-calculate based on resolution and limit.
        Returns list of dicts with keys: timestamp, open, high, low, close, volume
        """
        symbol = symbol or config.SYMBOL
        resolution = resolution or config.TIMEFRAME
        limit = limit or config.CANDLE_FETCH_COUNT

        # Auto-calculate start/end if not provided
        if end is None:
            end = int(time.time())
        else:
            end = int(end)

        if start is None:
            # Parse resolution to seconds
            res_map = {
                "1m": 60, "3m": 180, "5m": 300, "15m": 900,
                "30m": 1800, "1h": 3600, "2h": 7200, "4h": 14400,
                "6h": 21600, "1d": 86400, "1w": 604800,
            }
            interval_seconds = res_map.get(resolution, 180)  # default 3m
            start = end - (interval_seconds * limit)
        else:
            start = int(start)

        params = {
            "symbol": symbol,
            "resolution": resolution,
            "start": start,
            "end": end,
        }

        result = self._get("/v2/history/candles", params=params)
        return result

    def get_orderbook(self, symbol=None):
        """
        Get L2 orderbook for spread calculation.
        GET /v2/l2orderbook/{symbol}
        """
        symbol = symbol or config.SYMBOL
        result = self._get(f"/v2/l2orderbook/{symbol}")
        return result

    def get_ticker(self, symbol=None):
        """Get ticker data for a product."""
        symbol = symbol or config.SYMBOL
        result = self._get(f"/v2/tickers/{symbol}")
        return result

    # ---------------------------------------------------------------
    # Account Data (Authenticated)
    # ---------------------------------------------------------------
    def get_wallet_balance(self):
        """
        Get wallet balances.
        GET /v2/wallet/balances
        """
        result = self._get("/v2/wallet/balances", auth=True)
        if result is None:
            logger.error("Wallet balance API returned None - check API keys and connectivity")
            return {"balance": 0, "available_balance": 0, "asset": "USD"}

        if isinstance(result, list):
            for wallet in result:
                asset = wallet.get("asset_symbol", "")
                # Delta India uses USD or USDT
                if asset in ("USDT", "USD"):
                    balance = float(wallet.get("balance", 0))
                    avail = float(wallet.get("available_balance", 0))
                    logger.info(f"Wallet balance found: {balance} {asset}")
                    return {
                        "balance": balance,
                        "available_balance": avail,
                        "asset": asset,
                    }
            logger.warning(f"No USD/USDT asset found in wallet balances: {[w.get('asset_symbol') for w in result]}")
        else:
            logger.error(f"Unexpected wallet balance response format: {type(result)}")

        return {"balance": 0, "available_balance": 0, "asset": "USD"}

    def get_position(self, product_id=None):
        """
        Get current position for a product.
        GET /v2/positions/margined
        """
        result = self._get("/v2/positions/margined", auth=True)
        if not result or not isinstance(result, list):
            return None

        if product_id is None:
            product_id = self.get_product_id()

        for pos in result:
            if pos.get("product_id") == product_id:
                size = int(pos.get("size", 0))
                if size != 0:
                    return {
                        "product_id": pos["product_id"],
                        "size": size,
                        "side": "long" if size > 0 else "short",
                        "entry_price": float(pos.get("entry_price", 0)),
                        "margin": float(pos.get("margin", 0)),
                        "unrealized_pnl": float(
                            pos.get("unrealized_pnl", 0)
                        ),
                        "liquidation_price": pos.get("liquidation_price"),
                        "raw": pos,
                    }
        return None

    # ---------------------------------------------------------------
    # Order Management (Authenticated)
    # ---------------------------------------------------------------
    def place_order(
        self,
        product_id,
        side,
        size,
        order_type="limit_order",
        limit_price=None,
        time_in_force="gtc",
        client_oid=None,
    ):
        """
        Place a new order.
        POST /v2/orders
        side: "buy" or "sell"
        order_type: "limit_order" or "market_order"
        """
        payload = {
            "product_id": product_id,
            "side": side,
            "size": size,
            "order_type": order_type,
        }
        if order_type == "limit_order" and limit_price is not None:
            payload["limit_price"] = str(limit_price)
        if time_in_force:
            payload["time_in_force"] = time_in_force
        if client_oid:
            payload["client_oid"] = client_oid

        logger.info(
            f"Placing {order_type} {side} order: size={size}, "
            f"price={limit_price}, product={product_id}"
        )
        return self._post("/v2/orders", payload)

    def edit_order(self, order_id, product_id, new_limit_price=None, new_size=None):
        """
        Edit an existing order.
        PUT /v2/orders
        """
        payload = {
            "id": order_id,
            "product_id": product_id,
        }
        if new_limit_price is not None:
            payload["limit_price"] = str(new_limit_price)
        if new_size is not None:
            payload["size"] = new_size

        return self._put("/v2/orders", payload)

    def cancel_order(self, order_id, product_id):
        """
        Cancel an order.
        DELETE /v2/orders
        """
        payload = {
            "id": order_id,
            "product_id": product_id,
        }
        return self._delete("/v2/orders", payload)

    def cancel_all_orders(self, product_id):
        """Cancel all open orders for a product."""
        payload = {
            "product_id": product_id,
            "cancel_limit_orders": True,
            "cancel_stop_orders": True,
        }
        return self._delete("/v2/orders/all", payload)

    def get_open_orders(self, product_id=None):
        """
        Get active orders.
        GET /v2/orders
        """
        params = {"state": "open"}
        if product_id:
            params["product_id"] = product_id

        result = self._get("/v2/orders", params=params, auth=True)
        return result if result else []

    def get_order(self, order_id):
        """Get order by ID."""
        return self._get(f"/v2/orders/{order_id}", auth=True)

    def close_position(self, product_id):
        """
        Close all positions for a product via market order.
        DELETE /v2/positions/close_all
        """
        payload = {"close_all_portfolio": False}
        # First check current position
        pos = self.get_position(product_id)
        if pos and pos["size"] != 0:
            # Place opposite market order
            side = "sell" if pos["side"] == "long" else "buy"
            size = abs(pos["size"])
            return self.place_order(
                product_id=product_id,
                side=side,
                size=size,
                order_type="market_order",
            )
        return None

    def close_partial_position(self, product_id, fraction=0.5):
        """Close a fraction of the current position."""
        pos = self.get_position(product_id)
        if pos and pos["size"] != 0:
            close_size = max(1, int(abs(pos["size"]) * fraction))
            side = "sell" if pos["side"] == "long" else "buy"
            return self.place_order(
                product_id=product_id,
                side=side,
                size=close_size,
                order_type="market_order",
            )
        return None

    # ---------------------------------------------------------------
    # Leverage
    # ---------------------------------------------------------------
    def set_leverage(self, product_id, leverage=None):
        """Set leverage for a product."""
        leverage = leverage or config.LEVERAGE
        payload = {
            "product_id": product_id,
            "leverage": str(leverage),
        }
        return self._post("/v2/orders/leverage", payload)

    def get_leverage(self, product_id):
        """Get current leverage for a product."""
        params = {"product_id": product_id}
        return self._get("/v2/orders/leverage", params=params, auth=True)

    # ---------------------------------------------------------------
    # Utility
    # ---------------------------------------------------------------
    def test_connection(self):
        """Test API connectivity and authentication."""
        # Test public endpoint
        ticker = self.get_ticker()
        if not ticker:
            return False, "Failed to fetch ticker (public API error)"

        # Test authenticated endpoint
        wallet = self.get_wallet_balance()
        if wallet["balance"] == 0 and wallet["available_balance"] == 0:
            logger.warning("Wallet balance is 0 — may be auth issue or empty account")

        return True, f"Connected! Balance: {wallet['balance']} {wallet['asset']}"
