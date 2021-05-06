import sys
import traceback
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Optional, Union, Type
from types import TracebackType

import asyncio
import threading

import aiohttp
import requests


CALLBACK_TYPE = Callable[[dict, "Request"], Any]
ON_FAILED_TYPE = Callable[[int, "Request"], Any]
ON_ERROR_TYPE = Callable[[Type, Exception, TracebackType, "Request"], Any]


class RequestStatus(Enum):
    """请求状态"""

    ready = 0       # 请求创建
    success = 1     # 处理成功
    failed = 2      # 处理失败
    error = 3       # 触发异常


class Request(object):
    """请求对象"""

    def __init__(
        self,
        method: str,
        path: str,
        params: dict,
        data: Union[dict, str, bytes],
        headers: dict,
        callback: CALLBACK_TYPE = None,
        on_failed: ON_FAILED_TYPE = None,
        on_error: ON_ERROR_TYPE = None,
        extra: Any = None,
    ):
        """"""
        self.method: str = method
        self.path: str = path
        self.callback: CALLBACK_TYPE = callback
        self.params: dict = params
        self.data: Union[dict, str, bytes] = data
        self.headers: dict = headers

        self.on_failed: ON_FAILED_TYPE = on_failed
        self.on_error: ON_ERROR_TYPE = on_error
        self.extra: Any = extra

        self.response: aiohttp.Response = None
        self.status: RequestStatus = RequestStatus.ready

    def __str__(self):
        """"""
        if self.response is None:
            status_code = "terminated"
        else:
            status_code = self.response.status

        return (
            "request : {} {} {} because {}: \n"
            "headers: {}\n"
            "params: {}\n"
            "data: {}\n"
            "response:"
            "{}\n".format(
                self.method,
                self.path,
                self.status.name,
                status_code,
                self.headers,
                self.params,
                self.data,
                "" if self.response is None else self.response.text,
            )
        )


class RestClient(object):
    """
    HTTP Client designed for all sorts of trading RESTFul API.
    * Reimplement sign function to add signature function.
    * Reimplement on_failed function to handle Non-2xx responses.
    * Use on_failed parameter in add_request function for individual Non-2xx response handling.
    * Reimplement on_error function to handle exception msg.
    """

    def __init__(self):
        """"""
        self.url_base: str = ""
        self._active: bool = False

        self.proxies: dict = None

        self.session: aiohttp.ClientSession = aiohttp.ClientSession()
        self.loop: asyncio.AbstractEventLoop = asyncio.get_event_loop()
        self.thread: threading.Thread = None

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
            self.proxy = f"http://{proxy_host}:{proxy_port}"

    def start(self, n: int = 3) -> None:
        """启动客户端的事件循环"""
        # 如果事件循环已经在运行，则无需再次启动
        if self.loop.is_running():
            return

        self.thread = threading.Thread(target=self._run)
        self.thread.start()

    def stop(self) -> None:
        """停止客户端的事件循环"""
        if not self.loop.is_running():
            return

        self.loop.stop()

    def join(self) -> None:
        """等待子线程退出"""
        if self.thread and self.thread.is_alive():
            self.thread.join()

    def add_request(
        self,
        method: str,
        path: str,
        callback: CALLBACK_TYPE,
        params: dict = None,
        data: Union[dict, str, bytes] = None,
        headers: dict = None,
        on_failed: ON_FAILED_TYPE = None,
        on_error: ON_ERROR_TYPE = None,
        extra: Any = None,
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

        coro = self._process_request(request)
        asyncio.run_coroutine_threadsafe(coro, self.loop)
        return request

    def _run(self) -> None:
        """在子线程中运行事件循环"""
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def sign(self, request: Request) -> None:
        """签名函数（由用户继承实现具体签名逻辑）"""
        return request

    def on_failed(self, status_code: int, request: Request) -> None:
        """请求失败的默认回调"""
        sys.stderr.write(str(request))

    def on_error(
        self,
        exception_type: type,
        exception_value: Exception,
        tb,
        request: Optional[Request],
    ) -> None:
        """
        请求触发异常的默认回调"""
        sys.stderr.write(
            self.exception_detail(exception_type, exception_value, tb, request)
        )
        sys.excepthook(exception_type, exception_value, tb)

    def exception_detail(
        self,
        exception_type: type,
        exception_value: Exception,
        tb,
        request: Optional[Request],
    ) -> None:
        """将异常信息转化生成字符串"""
        text = "[{}]: Unhandled RestClient Error:{}\n".format(
            datetime.now().isoformat(), exception_type
        )
        text += "request:{}\n".format(request)
        text += "Exception trace: \n"
        text += "".join(
            traceback.format_exception(exception_type, exception_value, tb)
        )
        return text

    async def _process_request(self, request: Request) -> None:
        """发送请求到服务器，并对返回进行后续处理"""
        try:
            request = self.sign(request)

            url = self.make_full_url(request.path)

            async with self.session.request(
                request.method,
                url,
                headers=request.headers,
                params=request.params,
                data=request.data,
                proxy=self.proxy
            ) as response:
                request.response = response
                status_code = response.status
                if status_code // 100 == 2:  # 2xx codes are all successful
                    if status_code == 204:
                        json_body = None
                    else:
                        json_body = await response.json()

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
            t, v, tb = sys.exc_info()
            if request.on_error:
                request.on_error(t, v, tb, request)
            else:
                self.on_error(t, v, tb, request)

    def make_full_url(self, path: str) -> str:
        """
        生成完整的请求路径
        如: make_full_url("/get") == "http://xxxxx/get"
        """
        url: str = self.url_base + path
        return url

    def request(
        self,
        method: str,
        path: str,
        params: dict = None,
        data: dict = None,
        headers: dict = None,
    ) -> requests.Response:
        """同步请求函数（基于requests库）"""
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
