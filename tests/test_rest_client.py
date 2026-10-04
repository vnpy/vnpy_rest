from vnpy_rest.rest_client import Request, RestClient


class FakeResponse:
    def __init__(self, status_code: int, payload: dict | None) -> None:
        self.status_code: int = status_code
        self.text: str = ""
        self._payload: dict | None = payload

    def json(self) -> dict | None:
        return self._payload


class FakeSession:
    def __init__(self) -> None:
        self.method: str = ""
        self.url: str = ""
        self.headers: dict | None = None
        self.params: dict | None = None
        self.data: dict | str | None = None
        self.proxies: dict | None = None

    def request(
        self,
        method: str,
        url: str,
        headers: dict | None = None,
        params: dict | None = None,
        data: dict | str | None = None,
        proxies: dict | None = None,
    ) -> FakeResponse:
        self.method = method
        self.url = url
        self.headers = headers
        self.params = params
        self.data = data
        self.proxies = proxies
        return FakeResponse(200, {"status": "ok"})


class SigningRestClient(RestClient):
    def sign(self, request: Request) -> Request:
        headers: dict = dict(request.headers or {})
        headers["X-Sign"] = f"{request.method} {request.path}"
        request.headers = headers
        return request


def keep_callback(data: dict | None, request: Request) -> None:
    return None


def test_add_request_keeps_method_path_params_and_body() -> None:
    client: RestClient = RestClient()
    request: Request = client.add_request(
        "GET",
        "/api/position",
        keep_callback,
        params={"vt_symbol": "rb2510.SHFE"},
        data={"unused": False},
        headers={"Accept": "application/json"},
    )

    queued: Request = client.queue.get_nowait()
    assert queued is request
    assert request.method == "GET"
    assert request.path == "/api/position"
    assert request.params == {"vt_symbol": "rb2510.SHFE"}
    assert request.data == {"unused": False}
    assert request.headers == {"Accept": "application/json"}
    assert client.active is False


def test_process_request_sends_signed_url_params_and_body() -> None:
    client: SigningRestClient = SigningRestClient()
    client.init("https://example.invalid", "127.0.0.1", 9)
    session: FakeSession = FakeSession()
    seen: list[tuple[dict | None, Request]] = []

    def capture(data: dict | None, request: Request) -> None:
        seen.append((data, request))

    request: Request = Request(
        "POST",
        "/api/order",
        {"symbol": "rb2510"},
        {"volume": 2, "price": 3510},
        {"Content-Type": "application/json"},
        capture,
    )
    client.process_request(request, session)  # type: ignore[arg-type]

    assert session.method == "POST"
    assert session.url == "https://example.invalid/api/order"
    assert session.params == {"symbol": "rb2510"}
    assert session.data == {"volume": 2, "price": 3510}
    assert session.headers == {
        "Content-Type": "application/json",
        "X-Sign": "POST /api/order",
    }
    assert session.proxies == {
        "http": "http://127.0.0.1:9",
        "https": "http://127.0.0.1:9",
    }
    assert seen == [({"status": "ok"}, request)]
