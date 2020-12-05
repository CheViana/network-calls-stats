import contextlib
from functools import wraps, partial
import requests
import socket
import time
import asyncio

from requests.exceptions import RequestException
from yarl import URL


# ----------------------------- Sending stats to Telegraf -----------------------------------


STATS_UDP_ADDR = ('localhost', 8094)


def prepare_str_for_telegraf(value):
    if not isinstance(value, str):
        return value

    # there could be issues with some special chars in metric name, value or tags
    # replace ':', '_', '|' with '-'
    # https://github.com/influxdata/telegraf/issues/3508
    return str(value).replace(':', '-').replace('_', '-').replace('|', '-')


def format_measurement_influxline(metric_name, metric_value, tags):
    tags_str = ''
    if tags:
        tags = {
            prepare_str_for_telegraf(k): prepare_str_for_telegraf(v) for k, v in tags.items()
        }
        tags_strs = [
            f'{tag_key}={tag_value}' for tag_key, tag_value in tags.items()
        ]
        tags_str = (',' + ','.join(tags_strs))
    metric_value = prepare_str_for_telegraf(metric_value)
    metric_name = prepare_str_for_telegraf(metric_name)
    return f'{metric_name}{tags_str} value={metric_value}\n'


def send_stats(metric_name, metric_value, tags=None):
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.sendto(
            format_measurement_influxline(
                metric_name,
                metric_value,
                tags
            ).encode(),
            STATS_UDP_ADDR
        )
        print(f'Reported stats: {metric_name}={metric_value}, tags={tags}')
        sock.close()
    except socket.error as e:
        print(f'Got error: {e}')


# ------------------ Profiling context manager and decorator ------------------------

@contextlib.contextmanager
def profiler(metric_name, **tags):
    start = time.perf_counter()
    yield
    end = time.perf_counter()
    elapsed_time = int(round((end - start) * 1000))
    send_stats(metric_name, elapsed_time, tags)


def profile(f=None, metric_name=None):
    def actual_decorator(f):
        nonlocal metric_name
        if not metric_name:
            metric_name = f'{f.__name__}_exec_time'

        @wraps(f)
        def decorated_function(*args, **kwargs):
            with profiler(metric_name):
                return f(*args, **kwargs)

        @wraps(f)
        async def decorated_function_async(*args, **kwargs):
            with profiler(metric_name):
                return await f(*args, **kwargs)

        if asyncio.iscoroutinefunction(f):
            return decorated_function_async

        return decorated_function

    return actual_decorator(f) if f else actual_decorator


# ------------------ Requests send requests ------------------------


# def profile_request(start_time, response, *args, **kwargs):
#     elapsed_time = round((
#         time.perf_counter() - start_time
#     ) * 1000)
#     send_stats(
#         'requests_request_exec_time',
#         elapsed_time,
#         {'domain': URL(response.url).raw_host}
#     )


def get_response_text(url):
    try:
        start_time = time.perf_counter()
        def profile_request(response, *args, **kwargs):
            elapsed_time = round((time.perf_counter() - start_time) * 1000)
            send_stats('requests_request_exec_time', elapsed_time, {'domain': URL(response.url).raw_host})
        response = requests.get(
            url,
            hooks={'response': profile_request}
        )
        response.raise_for_status()
        return response.content.decode()
    except RequestException as e:
        send_stats(
            'requests_request_exception',
            1,
            {'domain': URL(url).raw_host, 'exception_class': e.__class__.__name__}
        )
        return f'Exception occured: {e}'


@profile
def call_python_and_mozilla_using_requests():
    # set domain to python1 to see errors
    py_response = get_response_text('https://www.python.org/')
    moz_response = get_response_text('https://www.mozilla.org/en-US/')
    return (
        f'Py response piece: {py_response[:60].strip()}... ,\n'
        f'Moz response piece: {moz_response[:60].strip()}...'
    )


# ----------------------------- main -----------------------------------


if __name__ == '__main__':
    while True:
        result = call_python_and_mozilla_using_requests()
        print(result)
        time.sleep(3)
