import sys
import traceback
from datetime import datetime
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


class Request:
    """
    请求对象

    method: API的请求方法（GET, POST, PUT, DELETE, QUERY）
    path: API的请求路径（不包含根地址）
    callback: 请求成功的回调函数
    params: 请求表单的参数字典
    data: 请求主体数据，如果传入字典会被自动转换为json
    headers: 请求头部的字典
    on_failed: 请求失败的回调函数
    on_error: 请求异常的回调函数
    extra: 任意其他数据（用于回调时获取）
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

    def __str__(self) -> str:
        """"""
        if self.response is None:
            status_code = "terminated"
        else:
            status_code = str(self.response.status_code)

        text: str = f"request : {self.method} {self.path} because {status_code}: \n"
        text += f"headers: {self.headers}\n"
        text += f"params: {self.params}\n"
        text += f"data: {self.data!r}\n"
        text += f"response: {self.response.text if self.response else ''}\n"
        return text


class RestClient:
    """
    针对各类REST API的异步客户端

    * 重载sign方法来实现请求签名逻辑
    * 重载on_failed方法来实现请求失败的标准回调处理
    * 重载on_error方法来实现请求异常的标准回调处理
    """

    def __init__(self) -> None:
        """构造函数"""
        self.url_base: str = ""
        self.active: bool = False

        self.queue: Queue = Queue()

        self.proxies: dict | None = None

    def init(
        self,
        url_base: str,
        proxy_host: str = "",
        proxy_port: int = 0
    ) -> None:
        """传入REST API的根地址，初始化客户端"""
        self.url_base = url_base

        if proxy_host and proxy_port:
            proxy = f"http://{proxy_host}:{proxy_port}"
            self.proxies = {"http": proxy, "https": proxy}

    def start(self, n: int = 5) -> None:
        """启动客户端的运行"""
        if self.active:
            return
        self.active = True

        self.pool: ThreadPool = Pool(n)
        self.pool.apply_async(self.run)

    def stop(self) -> None:
        """停止客户端的运行"""
        self.active = False

    def join(self) -> None:
        """等待子线程退出"""
        self.queue.join()

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
        """添加新的请求任务"""
        request: Request = Request(
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
        self.queue.put(request)
        return request

    def run(self) -> None:
        """每个线程中执行的任务处理"""
        try:
            session = requests.session()
            while self.active:
                try:
                    request = self.queue.get(timeout=1)
                    try:
                        self.process_request(request, session)
                    finally:
                        self.queue.task_done()
                except Empty:
                    pass
        except Exception:
            et, ev, tb = sys.exc_info()
            if et and ev and tb:
                self.on_error(et, ev, tb, None)

    def sign(self, request: Request) -> Request:
        """签名函数（由用户继承实现具体签名逻辑）"""
        return request

    def on_failed(self, status_code: int, request: Request) -> None:
        """请求失败的默认回调"""
        print("RestClient on failed" + "-" * 10)
        print(str(request))

    def on_error(
        self,
        exception_type: type[BaseException],
        exception_value: BaseException,
        tb: TracebackType,
        request: Request | None,
    ) -> None:
        """请求触发异常的默认回调"""
        try:
            print("RestClient on error" + "-" * 10)
            print(self.exception_detail(exception_type, exception_value, tb, request))
        except Exception:
            traceback.print_exc()

    def exception_detail(
        self,
        exception_type: type[BaseException],
        exception_value: BaseException,
        tb: TracebackType,
        request: Request | None,
    ) -> str:
        """将异常信息转化生成字符串"""
        text = f"[{datetime.now().isoformat()}]: Unhandled RestClient Error:{exception_type}\n"
        text += f"request:{request}\n"
        text += "Exception trace: \n"
        text += "".join(
            traceback.format_exception(exception_type, exception_value, tb)
        )
        return text

    def process_request(self, request: Request, session: requests.Session) -> None:
        """发送请求到服务器，并对返回进行后续处理"""
        try:
            # 对请求签名
            request = self.sign(request)

            # 发起同步请求
            response: Response = session.request(
                request.method,
                self.make_full_url(request.path),
                headers=request.headers,
                params=request.params,
                data=request.data,
                proxies=self.proxies,
            )

            # 绑定回报对象
            request.response = response

            # 解析回报数据
            status_code = response.status_code

            if status_code // 100 == 2:  # 2xx都代表成功
                json_body: dict | None = None

                if status_code != 204:
                    json_body = response.json()

                if request.callback:
                    request.callback(json_body, request)
            else:
                if request.on_failed:
                    request.on_failed(status_code, request)
                else:
                    self.on_failed(status_code, request)
        except Exception:
            # 获取异常信息
            et, ev, tb = sys.exc_info()

            # 推送异常回调
            if et and ev and tb:
                if request.on_error:
                    request.on_error(et, ev, tb, request)
                else:
                    self.on_error(et, ev, tb, request)

    def make_full_url(self, path: str) -> str:
        """组合根地址生成完整的请求路径"""
        return self.url_base + path

    def request(
        self,
        method: str,
        path: str,
        params: dict | None = None,
        data: dict | None = None,
        headers: dict | None = None,
    ) -> Response:
        """发起同步请求"""
        # 创建请求对象
        request: Request = Request(
            method,
            path,
            params,
            data,
            headers
        )

        # 对请求签名
        request = self.sign(request)

        # 发起同步请求
        response: Response = requests.request(
            request.method,
            self.make_full_url(request.path),
            headers=request.headers,
            params=request.params,
            data=request.data,
            proxies=self.proxies,
        )
        return response
