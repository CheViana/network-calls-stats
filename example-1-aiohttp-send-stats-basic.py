import socket
import asyncio

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


# ----------------------------- aiohttp profiling -----------------------------------


async def on_request_start(session, trace_config_ctx, params):
    trace_config_ctx.request_start = asyncio.get_event_loop().time()


async def on_request_end(session, trace_config_ctx, params):
    elapsed_time = round((
        asyncio.get_event_loop().time() - trace_config_ctx.request_start
    ) * 1000)
    send_stats(
        'aiohttp_request_exec_time',
        elapsed_time,
        {'domain': params.url.raw_host}
    )


async def on_request_exception(session, trace_config_ctx, params):
    send_stats(
        'aiohttp_request_exception',
        1,
        {'domain': params.url.raw_host, 'exception_class': params.exception.__class__.__name__}
    )


class Profiler(TraceConfig):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.on_request_start.append(on_request_start)
        self.on_request_end.append(on_request_end)
        self.on_request_exception.append(on_request_exception)


# ----------------------------- execute async backend requests -----------------------------------


async def call_and_consume_response(session, method, url, **request_kwargs):
    try:
        async with session.request(method, url, **request_kwargs) as response:
            response.raise_for_status()
            return await response.text()
    except ClientError as e:
        return f'Exception occured: {e}'


async def call_some_backends():
    async with ClientSession(trace_configs=[Profiler()]) as session:
        py_response, moz_response = await asyncio.gather(
            # change domain to python1 or set tiny timeout to see network errors
            call_and_consume_response(session, 'GET', 'https://www.python.org/'),
            call_and_consume_response(session, 'GET', 'https://www.mozilla.org/en-US/')
        )
        return (
            f'Py response piece: ...{py_response[:30]}... , '
            f'Moz response piece: ...{moz_response[:30]}...'
        )


def fetch_async_via_loop(*coroutines):
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        print('Setting new event loop')
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    futures = [asyncio.ensure_future(coro) for coro in coroutines]
    try:
        return loop.run_until_complete(asyncio.gather(*futures))
    finally:
        for future in futures:  # Cancel unfinished tasks
            if not future.done():
                print(f'Cancelling task {future}')
                future.cancel()


# ----------------------------- main -----------------------------------


if __name__ == '__main__':
    while True:
        result = fetch_async_via_loop(call_some_backends())
        print(result)
        fetch_async_via_loop(asyncio.sleep(3))
