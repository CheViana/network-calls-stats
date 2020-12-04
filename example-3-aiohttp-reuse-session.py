import socket
import asyncio
import contextlib
import time
import signal
from functools import wraps

from aiohttp import TraceConfig, ClientSession
from aiohttp.client_exceptions import ClientError


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
    """
    This profile decorator works for async and sync functions,
    and for class methods. Default metric name will be name of
    profiled function plus '_exec_time'.

    Usage:

        @profile(metric_name='my_exec_time')
        def something_that_takes_time(...):
            ...
    """
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


# ----------------------------- aiohttp profiling -----------------------------------
# https://docs.aiohttp.org/en/stable/tracing_reference.html


def compute_elapsed_and_send_stats(start_time, metric_name, params):
    elapsed_time = round((
        asyncio.get_event_loop().time() - start_time
    ) * 1000)
    tags = {}
    if hasattr(params, 'host'):
        tags['domain'] = params.host
    if hasattr(params, 'url'):
        tags['domain'] = params.url.raw_host
    send_stats(
        metric_name,
        elapsed_time,
        tags
    )


async def on_request_start(session, trace_config_ctx, params):
    trace_config_ctx.request_start = asyncio.get_event_loop().time()


async def on_request_end(session, trace_config_ctx, params):
    compute_elapsed_and_send_stats(
        trace_config_ctx.request_start,
        'aiohttp_request_exec_time',
        params
    )


async def on_connection_queued_start(session, trace_config_ctx, params):
    trace_config_ctx.connection_queued_start = asyncio.get_event_loop().time()


async def on_connection_queued_end(session, trace_config_ctx, params):
    compute_elapsed_and_send_stats(
        trace_config_ctx.connection_queued_start,
        'aiohttp_connection_queued_time',
        params
    )


async def on_connection_create_start(session, trace_config_ctx, params):
    trace_config_ctx.connection_create_start = asyncio.get_event_loop().time()


async def on_connection_create_end(session, trace_config_ctx, params):
    compute_elapsed_and_send_stats(
        trace_config_ctx.connection_create_start,
        'aiohttp_connection_create_time',
        params
    )


async def on_dns_resolvehost_start(session, trace_config_ctx, params):
    trace_config_ctx.dns_resolvehost_start = asyncio.get_event_loop().time()


async def on_dns_resolvehost_end(session, trace_config_ctx, params):
    compute_elapsed_and_send_stats(
        trace_config_ctx.dns_resolvehost_start,
        'aiohttp_dns_resolvehost_time',
        params
    )


async def on_request_redirect(session, trace_config_ctx, params):
    send_stats(
        'aiohttp_request_redirect',
        1,
        {'domain': params.url.raw_host}
    )


async def on_request_exception(session, trace_config_ctx, params):
    send_stats(
        'aiohttp_request_exception',
        1,
        {
            'domain': params.url.raw_host,
            'exception_class': params.exception.__class__.__name__
        }
    )


async def on_response_chunk_received(session, trace_config_ctx, params):
    send_stats(
        'aiohttp_response_chunk_received',
        len(params.chunk),
        {'domain': params.url.raw_host}
    )


async def on_connection_reuseconn(session, trace_config_ctx, params):
    send_stats(
        'aiohttp_connection_reuseconn',
        1
    )


async def on_dns_cache_hit(session, trace_config_ctx, params):
    send_stats(
        'aiohttp_dns_cache_hit',
        1,
        {'domain': params.host}
    )


async def on_dns_cache_miss(session, trace_config_ctx, params):
    send_stats(
        'aiohttp_dns_cache_miss',
        1,
        {'domain': params.host}
    )


class Profiler(TraceConfig):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.on_request_start.append(on_request_start)
        self.on_request_end.append(on_request_end)
        self.on_request_redirect.append(on_request_redirect)
        self.on_request_exception.append(on_request_exception)
        self.on_connection_queued_start.append(on_connection_queued_start)
        self.on_connection_queued_end.append(on_connection_queued_end)
        self.on_connection_create_start.append(on_connection_create_start)
        self.on_connection_create_end.append(on_connection_create_end)
        self.on_dns_resolvehost_start.append(on_dns_resolvehost_start)
        self.on_dns_resolvehost_end.append(on_dns_resolvehost_end)
        self.on_response_chunk_received.append(on_response_chunk_received)
        self.on_connection_reuseconn.append(on_connection_reuseconn)
        self.on_dns_cache_hit.append(on_dns_cache_hit)
        self.on_dns_cache_miss.append(on_dns_cache_miss)


# ----------------------------- execute async backend requests -----------------------------------


async def get_response_text(url, session):
    try:
        async with session.get(url) as response:
            response.raise_for_status()
            return await response.text()
    except ClientError as e:
        return f'Exception occured: {e}'


@profile
async def call_python_and_mozilla_using_aiohttp(session):
    py_response, moz_response = await asyncio.gather(
        # change domain to python1 or set tiny timeout to see network errors
        get_response_text('https://www.python.org/', session),
        get_response_text('https://www.mozilla.org/en-US/', session)
    )
    return (
        f'Py response piece: {py_response[:60].strip()}... ,\n'
        f'Moz response piece: {moz_response[:60].strip()}...'
    )


# ----------------------------- main -----------------------------------
# Adapted from https://www.roguelynn.com/words/asyncio-graceful-shutdowns/


async def main_async():
    async with ClientSession(trace_configs=[Profiler()]) as session:
        while True:
            result = await call_python_and_mozilla_using_aiohttp(session)
            print(result)
            await asyncio.sleep(3)


async def shutdown(signal, loop):
    # Finalize asyncio loop
    tasks = [
        t for t in asyncio.all_tasks() if t is not asyncio.current_task()
    ]
    [task.cancel() for task in tasks]
    print(f'Cancelling {len(tasks)} outstanding tasks')
    await asyncio.gather(*tasks, return_exceptions=True)
    loop.stop()
    print('Stopped loop')


if __name__ == '__main__':
    loop = asyncio.get_event_loop()
    signals = (signal.SIGHUP, signal.SIGTERM, signal.SIGINT)
    for s in signals:
        loop.add_signal_handler(s, lambda s=s: asyncio.create_task(shutdown(s, loop)))
    try:
        loop.create_task(main_async())
        loop.run_forever()
    finally:
        loop.close()
        print('Closed loop')
