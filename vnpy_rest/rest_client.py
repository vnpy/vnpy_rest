import sys
import traceback
from datetime import datetime
from enum import Enum
from multiprocessing.dummy import Pool
from multiprocessing.pool import ThreadPool
from queue import Empty, Queue
from typing import Any
from collections.abc import Callable
from types import TracebackType

import requests


CALLBACK_TYPE = Callable[[dict | None, "Request"], Any]
ON_FAILED_TYPE = Callable[[int, "Request"], Any]
ON_ERROR_TYPE = Callable[[type[BaseException], BaseException, TracebackType, "Request"], Any]


Response = requests.Response


class RequestStatus(Enum):
    """"""

    ready = 0       # Request created
    success = 1     # Request successful (status code 2xx)
    failed = 2      # Request failed (status code not 2xx)
    error = 3       # Exception raised


class Request:
    """
    Request object for status check.
    """

    def __init__(
        self,
        method: str,
        path: str,
        params: dict | None,
        data: dict | str | None,
        headers: dict | None,
        callback: CALLBACK_TYPE | None = None,
        on_failed: ON_FAILED_TYPE | None = None,
        on_error: ON_ERROR_TYPE | None = None,
        extra: Any | None = None,
    ):
        """"""
        self.method: str = method
        self.path: str = path
        self.callback: CALLBACK_TYPE | None = callback
        self.params: dict | None = params
        self.data: dict | str | None = data
        self.headers: dict | None = headers

        self.on_failed: ON_FAILED_TYPE | None = on_failed
        self.on_error: ON_ERROR_TYPE | None = on_error
        self.extra: Any | None = extra

        self.response: requests.Response | None = None
        self.status: RequestStatus = RequestStatus.ready

    def __str__(self) -> str:
        """"""
        if self.response is None:
            status_code = "terminated"
        else:
            status_code = str(self.response.status_code)

        text: str = f"request : {self.method} {self.path} {self.status.name} because {status_code}: \n"
        text += f"headers: {self.headers}\n"
        text += f"params: {self.params}\n"
        text += f"data: {self.data!r}\n"
        text += f"response: {self.response.text if self.response else ''}\n"
        return text


class RestClient:
    """
    HTTP Client designed for all sorts of trading RESTFul API.
    * Reimplement sign function to add signature function.
    * Reimplement on_failed function to handle Non-2xx responses.
    * Use on_failed parameter in add_request function for individual Non-2xx response handling.
    * Reimplement on_error function to handle exception msg.
    """

    def __init__(self) -> None:
        """"""
        self.url_base: str = ""
        self._active: bool = False

        self._queue: Queue = Queue()

        self.proxies: dict | None = None

    def init(
        self,
        url_base: str,
        proxy_host: str = "",
        proxy_port: int = 0
    ) -> None:
        """
        Init rest client with url_base which is the API root address.
        e.g. "https://www.bitmex.com/api/v1/"
        """
        self.url_base = url_base

        if proxy_host and proxy_port:
            proxy = f"http://{proxy_host}:{proxy_port}"
            self.proxies = {"http": proxy, "https": proxy}

    def start(self, n: int = 3) -> None:
        """
        Start rest client with session count n.
        """
        if self._active:
            return

        self._active = True

        self._pool: ThreadPool = Pool(n)
        self._pool.apply_async(self._run)

    def stop(self) -> None:
        """
        Stop rest client immediately.
        """
        self._active = False

    def join(self) -> None:
        """
        Wait till all requests are processed.
        """
        self._queue.join()

    def add_request(
        self,
        method: str,
        path: str,
        callback: CALLBACK_TYPE,
        params: dict | None = None,
        data: dict | str | None = None,
        headers: dict | None = None,
        on_failed: ON_FAILED_TYPE | None = None,
        on_error: ON_ERROR_TYPE | None = None,
        extra: Any | None = None,
    ) -> Request:
        """
        Add a new request.
        :param method: GET, POST, PUT, DELETE, QUERY
        :param path: url path for query
        :param callback: callback function if 2xx status, type: (dict, Request)
        :param params: dict for query string
        :param data: Http body. If it is a dict, it will be converted to form-data. Otherwise, it will be converted to bytes.
        :param headers: dict for headers
        :param on_failed: callback function if Non-2xx status, type, type: (code, dict, Request)
        :param on_error: callback function when catching Python exception, type: (etype, evalue, tb, Request)
        :param extra: Any extra data which can be used when handling callback
        :return: Request
        """
        request = Request(
            method,
            path,
            params,
            data,
            headers,
            callback,
            on_failed,
            on_error,
            extra,
        )
        self._queue.put(request)
        return request

    def _run(self) -> None:
        """"""
        try:
            session = requests.session()
            while self._active:
                try:
                    request = self._queue.get(timeout=1)
                    try:
                        self._process_request(request, session)
                    finally:
                        self._queue.task_done()
                except Empty:
                    pass
        except Exception:
            et, ev, tb = sys.exc_info()
            if et and ev and tb:
                self.on_error(et, ev, tb, None)

    def sign(self, request: Request) -> Request:
        """
        This function is called before sending any request out.
        Please implement signature method here.
        @:return (request)
        """
        return request

    def on_failed(self, status_code: int, request: Request) -> None:
        """
        Default on_failed handler for Non-2xx response.
        """
        sys.stderr.write(str(request))

    def on_error(
        self,
        exception_type: type[BaseException],
        exception_value: BaseException,
        tb: TracebackType,
        request: Request | None,
    ) -> None:
        """
        Default on_error handler for Python exception.
        """
        text: str = self.exception_detail(exception_type, exception_value, tb, request)
        sys.stderr.write(text)

        sys.excepthook(exception_type, exception_value, tb)

    def exception_detail(
        self,
        exception_type: type[BaseException],
        exception_value: BaseException,
        tb: TracebackType,
        request: Request | None,
    ) -> str:
        text = f"[{datetime.now().isoformat()}]: Unhandled RestClient Error:{exception_type}\n"
        text += f"request:{request}\n"
        text += "Exception trace: \n"
        text += "".join(
            traceback.format_exception(exception_type, exception_value, tb)
        )
        return text

    def _process_request(
        self, request: Request, session: requests.Session
    ) -> None:
        """
        Sending request to server and get result.
        """
        try:
            request = self.sign(request)

            url = self.make_full_url(request.path)

            response = session.request(
                request.method,
                url,
                headers=request.headers,
                params=request.params,
                data=request.data,
                proxies=self.proxies,
            )
            request.response = response
            status_code = response.status_code
            if status_code // 100 == 2:  # 2xx codes are all successful
                json_body: dict | None = None

                if status_code != 204:
                    json_body = response.json()

                if request.callback:
                    request.callback(json_body, request)

                request.status = RequestStatus.success
            else:
                request.status = RequestStatus.failed

                if request.on_failed:
                    request.on_failed(status_code, request)
                else:
                    self.on_failed(status_code, request)
        except Exception:
            request.status = RequestStatus.error
            et, ev, tb = sys.exc_info()

            if et and ev and tb:
                if request.on_error:
                    request.on_error(et, ev, tb, request)
                else:
                    self.on_error(et, ev, tb, request)

    def make_full_url(self, path: str) -> str:
        """
        Make relative api path into full url.
        eg: make_full_url("/get") == "http://xxxxx/get"
        """
        url = self.url_base + path
        return url

    def request(
        self,
        method: str,
        path: str,
        params: dict | None = None,
        data: dict | None = None,
        headers: dict | None = None,
    ) -> requests.Response:
        """
        Add a new request.
        :param method: GET, POST, PUT, DELETE, QUERY
        :param path: url path for query
        :param params: dict for query string
        :param data: dict for body
        :param headers: dict for headers
        :return: requests.Response
        """
        request = Request(
            method,
            path,
            params,
            data,
            headers
        )
        request = self.sign(request)

        url = self.make_full_url(request.path)

        response = requests.request(
            request.method,
            url,
            headers=request.headers,
            params=request.params,
            data=request.data,
            proxies=self.proxies,
        )
        return response
