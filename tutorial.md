# Monitoring network calls in Python using TIG stack

Web applications are known to perform backend calls. There's big operational and business value in monitoring how much time backend calls take. Let's look at some code examples that capture and report backend call time using popular Python networking libraries.

### What I'm going to explore in this blogpost

I'm going to compare how request timings look for fetching HTML pages using `requests` library and for asyncronously fetching same HTML pages using `aiohttp` library, and attempt to visualize the differences in timings.

To monitor request timings we will use Telegraf, InfluxDB and Grafana stack. These tools are very easy to setup locally, and could be used in production environment.

See chapter 'Running code examples' below on how to run example code and setup monitoring infrastructure.
Code for all examples available in [repo](https://github.com/CheViana/network-calls-stats/).

### What I'm not going to explore in this blogpost

To be fair, `requests` library also provides ways for simultaneous requests execution, in form of `requsts-threads`, but I'm not going look at that tool in this post, or at other numerous ways to achieve non-blocking I/O in Python.

I'm not aiming to cover which networking library is best for production use, or which ready-made monitoring solution is best for production use.

There are multiple tools that provide production-ready web application performance monitoring: backend call time, database query execution time, cache hits, etc. Those are often paid-for, easy to use and don't pollute business code with metrics reporting. Those also might not support your networking library, or generally be not a good fit, like when backend IP changes and the tool uses IPs to distinguish between backends. I suggest to look into ready-made solutions and use your best judgement on what to use.


## Example 0: monitor `requests` request time

Let's dive into first code example. Here's what it does:
- in forever loop, executes two HTTP requests using `requests` Python library
- reports request time and request exceptions to Telegraf

Here's execution time results on dashboard:
[tutorial-images/example-0-request-time-results.png]

Full code of example 0 is [here](https://github.com/CheViana/network-calls-stats/blob/master/example-0-requests-send-stats.py).

High-level execution flow can be followed from `main` part of program:
```
if __name__ == '__main__':
    while True:
        result = call_python_and_mozilla_using_requests()
        print(result)
        time.sleep(3)
```

`call_python_and_mozilla_using_requests()` and pause 3 seconds, repeat foverer.

Inside `call_python_and_mozilla_using_requests` two simple HTTP requests are performed one by one, and their response text used to compose result:
```
def call_python_and_mozilla_using_requests():
    py_response = get_response_text('https://www.python.org/')
    moz_response = get_response_text('https://www.mozilla.org/en-US/')
    return (
        f'Py response piece: {py_response[:60].strip()}... ,\n'
        f'Moz response piece: {moz_response[:60].strip()}...'
    )
```

`get_response_text` function executes HTTP request for given URL, with primitive exception handling, and hook to report request execution time:
```
def profile_request(start_time, response, *args, **kwargs):
    elapsed_time = round((
        time.perf_counter() - start_time
    ) * 1000)
    send_stats(
        'requests_request_exec_time',
        elapsed_time,
        {'domain': URL(response.url).raw_host}
    )


def get_response_text(url):
    try:
        response = requests.get(
            url,
            hooks={'response': partial(profile_request, time.perf_counter())}
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
```

This code uses `requests` library ([docs](https://requests.readthedocs.io/en/master/)). Basic usage to get text content from URL is following:
```
response = requests.get(url).content.decode()
```

`requests.get` accepts optional `hooks` argument, where we specified function to be called after request is completed. 
`partial(profile_request, time.perf_counter())` is itself a function. It's same function as `profile_request` but first argument is already filled in - `time.perf_counter()` passed as `start_time`. Read more about [partial functions in Python](https://docs.python.org/3/library/functools.html#functools.partial).
`time.perf_counter()` is used to measure execution time in Python, [more about it](https://docs.python.org/3/library/time.html#time.perf_counter).
`profile_request` function computes elapsed time based on `start_time` provided and current time. `elapsed_time` is in milliseconds, `time.perf_counter()` return microseconds. 
`send_stats` function is used to report measurement to Telegraf: metric name is `'requests_request_exec_time'`, metric value is time request execution took, tags include additional useful information (domain of URL).
`get_response_text` also invokes `send_stats` when exception occurs, passing different metric name this time - `'requests_request_exception'`.

### Sending stats

`profile_request` function, as well as `profile` decorator, send stats to Telegraf using function `send_stats`.
I have [another post](https://dev.to/cheviana/reporting-measurements-from-python-code-in-real-time-4g5) that describes ways to send stats from Python program to Telegraf.

In short, `send_stats` accepts metric name, metric value and tags dictionary. Those are converted to one string, and sent to socket on which Telegraf listens for measurement data. Telegraf sends received metrics to database (InfluxDB). Grafana dashboards query database to put a dot on graph for each request execution time reported.


### `profile` decorator

A piece of code which is decorator suitable for any function (async, sync, method of class or pure function) is adapted here to profile function that is decorated. 
`profile` decorator is used to profile total execition time of functions `call_python_and_mozilla_using_requests` and `call_python_and_mozilla_using_aiohttp` (following examples).
Don't confuse with another useful tool - [line_profiler](https://github.com/rkern/line_profiler) - that also provides `profile` decorator.

### Results on dashboard

Let's run this example and setup all the monitoring tools (See chapter 'Running code examples' below on how to run example code and setup monitoring infrastructure).

We can configure a panel that shows time request execution took:
[tutorial-images/example-0-results-and-config.png]

Blue dots of total execution time roughly correspond to sum of time request to `python.org` and request to `mozilla.org` took (green and yellow dots), and measures at approximately 150 msec on average.

### Need more exceptions

If we change 'www.python.org' to 'www.python1.org' in function `call_python_and_mozilla_using_requests`, exceptions appear in terminal output, and exception metrics are sent to Telegraf:
```
    Reported stats: aiohttp_request_exception=1, tags={'domain': 'www.python1.org', 'exception_class': 'ClientConnectorError'}
    'Py response piece: ...Exception occured: Cannot conn... 
```

Configure separate Grafana panel to see exceptions on dashboard:
[tutorial-images/example-0-1-exceptions-dashboard-and-config.png]

Exception class is sent as tag along with metric value. This gives us ability to plot different lines in panel for exceptions of different classes. To achieve this, pick 'group by - tag(exception_class)' when editing request exceptions query in Grafana panel.


### Example 0 improved: reuse connection

Code of example 0 can be improved to reuse same connection for calls performed in that forever running `while` loop - here's [improved version](https://github.com/CheViana/network-calls-stats/blob/master/example-0-plus-requests-reuse-conn.py).

Main difference from original example 0:
```
...
session = requests.Session()
while True:
    result = call_python_and_mozilla_using_requests(session)
...
```
This moves connection creation out of `while` loop, now connection is established once and for all.

Let's compare how much time request execution takes when connection is reused:
[tutorial-images/example-0-plus-session-reuse-results.png]

On the left are dots-measurements for original version of Example 0, on the right - for improved version. Can definitely notice how total execution time get lower, below 100 msec on average. 


## Example 1: monitor `aiohttp` request time

Let's dive into next code example. Here's what it does:
- in forever loop, executes two asyncronous HTTP requests using `aiohttp`
- hooks into `aiohttp` signals for request execution
- reports request time and request exceptions to Telegraf

Here's execution time results on dashboard:
[tutorial-images/example-1-request-time-results.png]

Full code of Example 1 can be found in [example-1-aiohttp-send-stats-basic.py](https://github.com/CheViana/network-calls-stats/blob/master/example-1-aiohttp-send-stats-basic.py).

### The tale of two HTTP requests

Let's start with function `call_python_and_mozilla_using_aiohttp` that executes two asyncronous HTTP requests and prints out bits of response content received (much like `call_python_and_mozilla_using_requests` from Example 0):

```
async def get_response_text(url):
    try:
        async with ClientSession(trace_configs=[Profiler()]) as session:
            async with session.get(url) as response:
                response.raise_for_status()
                return await response.text()
    except ClientError as e:
        return f'Exception occured: {e}'

@profile
async def call_python_and_mozilla_using_aiohttp():
        py_response, moz_response = await asyncio.gather(
            get_response_text('https://www.python.org/'),
            get_response_text('https://www.mozilla.org/en-US/')
        )
        return (
            f'Py response piece: {py_response[:60].strip()}... ,\n'
            f'Moz response piece: {moz_response[:60].strip()}...'
        )
```

This code uses `aiohttp` library ([docs](https://docs.aiohttp.org/en/stable/client.html)). Basic usage to get text content from URL is following:
```
async with ClientSession() as session:
    async with session.get(url) as response:
        return await response.text()
```

Which is basically what happens in `get_response_text`. `get_response_text` also calls `response.raise_for_status()` which raises exception when response status code is error code or timeout occurs (`aiohttp` [docs on exceptions](https://docs.aiohttp.org/en/stable/client_reference.html#client-exceptions)). Exception is silenced in `get_response_text`, so `get_response_text` always returns `str`, either with response content or with exception message.

`call_python_and_mozilla_using_aiohttp` takes care of callings 2 URLs using `asyncio.gather` (if it's all very new to you, suggest to [read about tasks and coroutines more](https://python.readthedocs.io/en/latest/library/asyncio-task.html)). Execution order is following:

first request is sent --> second request is sent --> wait for either one of requests to complete --> first response is received --> second response is received

Total execution time is approximately the time of the longest request out of these two. You're probably aware that this is called non-blocking IO: IO operation frees execution thread, until it needs it again, instead of blocking.

Traditional, not asyncronous, blocking IO, has following execution order:

first request is sent --> wait for first request to complete --> first response is received --> second request is sent --> wait for second request to complete --> second response is received

And total execution time is approximately the sum of both requests execution time. For positive integers, it's always true that `A + B > MAX(A, B)` hence asyncronous execution takes less time than syncronous. Provided unlimited CPU was made available to Python program in both cases, async and sync.

Same `profile` decorator is used to measure total execution time of both requests.

On panel that shows requests execition time and their total execution time, it's possible to notice that total execution time `call_python_and_mozilla_using_aiohttp_exec_time` almost matches the longer-executing request time:
[tutorial-images/example-1-requests-and-total-time.png]

Total execution time for both requests is 75-100 msec.
Next we're going to look at how execution time of each `aiohttp` request is reported.


### `aiohttp` requests signals

`aiohttp` provides a way to execute custom function when HTTP request execution progresses through lifecycle stages: before request is sent, when connection is established, after response chunk is received, etc.

For that, special object-tracer is passed to `aiohttp.ClientSession` - `trace_configs`:
```
class Profiler(TraceConfig):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.on_request_start.append(on_request_start)
        self.on_request_end.append(on_request_end)
        self.on_request_exception.append(on_request_exception)

...
async with ClientSession(trace_configs=[Profiler()]) as session:
...
```

`Profiler` is subclass of `aiohttp.TraceConfig`. It "hooks up" functions that are going to be executed when request starts (`on_request_start`), when it ends (`on_request_end`), and when request exception is encountered (`on_request_exception`):
```
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
```

Notice how timestamp of request start is computed:
```
asyncio.get_event_loop().time()
```
It is recommended to use event loop’s internal monotonic clock to compute timedeltas in asyncronous code, rather than `time.now()` or `time.perf_counter()`.

Function-hooks have arguments `session, trace_config_ctx, params`. 
`session` is instance of `aiohttp.ClientSession`. 
`trace_config_ctx` is context that is passed through all these callbacks, and custom values call be added to it when request is made:
```
await session.get(url, trace_request_ctx={'flag': 'red'})
...

async def on_request_end(session, trace_config_ctx, params):
    if trace_config_ctx.trace_request_ctx['flag'] == 'red':
        ....
```

`on_request_start` sets request start time on `trace_config_ctx`:
```
trace_config_ctx.request_start = asyncio.get_event_loop().time()
```

`on_request_end` uses `trace_config_ctx.request_start` value to compute total time request took.

`params` argument in `on_request_end` is `aiohttp.TraceRequestEndParams` and as such has `url` property. `url` property is of `yarl.URL` type. `params.url.raw_host` returns domain of URL which was requested. Domain is sent as tag for metric, and this makes it possible to plot separate lines for request execution time for requests to different domains.


### Main thing

When script is launched from command line, following code fires:
```
async def main_async():
    while True:
        result = await call_python_and_mozilla_using_aiohttp()
        print(result)
        await asyncio.sleep(3)
```

This will call `call_python_and_mozilla_using_aiohttp`, then sleep 3 seconds. Then call again, forever. Until program is stopped.

To call async function in sync execution context special tooling is used, which is adapted from [another publication](https://www.roguelynn.com/words/asyncio-graceful-shutdowns/). I'm not going to dive into Python's asyncronous ways in this post. Read more about Python's [asyncio](https://python.readthedocs.io/en/latest/library/asyncio.html), it's pretty cool.


### Compare results for Example 0 and 1

[tutorial-images/example-0-1-compare-results.pngs.png]
Connection is not reused for both cases here. Execution time for async version is lower.


## Example 2: more, more stats

`aiohttp` provides hooks to measure more than just request execution time and request exceptions.

We aslo can report stats for:
- DNS resolution time
- DNS cache hit/miss
- waiting for available connection time
- connection establishing time
- connection being reused
- redirect happening
- response content chunk received
- request chunk sent

Documentation on tracing in `aiohttp` is [here](https://docs.aiohttp.org/en/stable/tracing_reference.html).
Impressive, isn't it?

Let's add more listeners - to all of those hooks:

```
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
```

I won't bore you with code for each function like `on_dns_resolvehost_end`. Full code of Example 2 is [here](https://github.com/CheViana/network-calls-stats/blob/master/example-2-aiohttp-send-more-stats.py).

Reported stats on dashboard for example 2:
[tutorial-images/example-2-results.png]

We can see that DNS resolution takes couple of milliseconds and happens for every call, and connection establishing takes 30-40 msec and happens for every call. Also, that DNS cache is not hit, DNS is resolved for every call.

We can definitely improve on that - in Example 3.

## Example 3: `aiohttp` reuse session

Let's modify Example 2 code so that `ClientSession` is created once, outside `while` loop:
```
async def main_async():
    async with ClientSession(trace_configs=[Profiler()]) as session:
        while True:
            result = await call_python_and_mozilla_using_aiohttp(session)
            print(result)
            await asyncio.sleep(3)
```

And check out how stats look now:
[tutorial-images/example-3-results.png]

There's only one dot for connection establishing, and one per DNS resoltion per domain. There's plenty of dots for connection reuse event.
Total execution time is below 50 msec. Cool.

Full source code of Example 3 is [here](https://github.com/CheViana/network-calls-stats/blob/master/example-3-aiohttp-reuse-session.py).

Although it looks pretty neat, it might not be possible to using async context manager outside the loop in real-life applications. That's why let's try example 4.

## Example 4: aiohttp.TCPConnector

Great caution is advised with this example.
It's just a piece of code to have fun with, not to be used in production.

In this example, we're going to make use of `aiohttp`'s `TCPConnector` object, which is a wrap around connection pool ([docs](https://docs.aiohttp.org/en/stable/client_reference.html#tcpconnector)). We're going to reuse same connector while creating new `ClientSession` for every call.
`aiohttp` docs recommended way to reuse connections is like in Example 3, so better stick to that.

Full source code of Example 4 is [here](https://github.com/CheViana/network-calls-stats/blob/master/example-4-aiohttp-reuse-conn.py).

Here's how main entry point of program looks in Example 4:
```
async def main_async():
    await create_connector()
    while True:
        result = await call_python_and_mozilla_using_aiohttp()
        print(result)
        await asyncio.sleep(3)


async def shutdown(signal, loop):
    # Close asiohttp connector
    await close_connector()
    ...

if __name__ == '__main__':
    loop = asyncio.get_event_loop()
    signals = (signal.SIGHUP, signal.SIGTERM, signal.SIGINT)
    for s in signals:
        loop.add_signal_handler(s, lambda s=s: asyncio.create_task(shutdown(s, loop)))
    ...

```

This code creates connector before `while` loop happens. When program is shut down, `shutdown` is called, which closes connector. Program prints to terminal on shutdown:
```
^CClosed connector
Cancelling 1 outstanding tasks
Stopped loop
Closed loop
```

The created connector is used in `get_response_text` function, passed as an argument to `ClientSession`, along with `connector_owner=False`.
Generally, it's not best idea to store `ClientSession` or `TCPConnector` in thread context, because finalization (connection releasing) could not happen, if program terminates unexpectedly. Example 4 handles connection closing when process is killed or shut down. In some other cases connection might not be closed correctly or left hanging. Try to put `raise ValueError()` somewhere in Example 4 `call_python_and_mozilla_using_aiohttp` and see what happens.

Let's check how stats look for Example 4:
[tutorial-images/example-4-results.png]

Pretty much the same as for Example 3, but *way more dangerous*.


## Running code examples

### Prerequirements: Python

Install Python3: https://docs.python-guide.org/starting/install3/ .
Make sure when you run
```
python --version
```
It prints out 'python3.' (could be 'python3.9', or 'python3.7', etc).

### Prerequirements: Install and launch Telegraf, InfluxDB, Grafana

Visit https://portal.influxdata.com/downloads/ for information on how to install InfluxDB and Telegraf.
Visit https://grafana.com/grafana/download for information on how to install Grafana.

Run Telegraf, InfluxDB, Grafana (each in it's own shell tab):
```
telegraf -config telegraf.conf
```
Config file telegraf.conf is provided in [examples repo](https://github.com/CheViana/network-calls-stats/blob/master/telegraf.conf).

```
influxd -config /usr/local/etc/influxdb.conf
```

```
cd grafana-7.1.0/
bin/grafana-server
```

To see results on dashboard need to keep Telegraf, InfluxDB, Grafana running while running Python scripts.

### Examples repository

Checkout [repository](https://github.com/CheViana/network-calls-stats/) with code examples and Telegraf config.

### Python dependencies

It's best to create virtual environment to keep dependencies of project isolated from system Python packages, and dependencies of other projects. For that, I suggest to use [virtualenv](https://virtualenv.pypa.io/en/latest/installation.html) and [virtualenvwrapper](https://virtualenvwrapper.readthedocs.io/en/latest/install.html). Need to install these tools if you don't have them installed already.

Create virtual environment using `virtualenvwrapper`:
```
mkvirtualenv network-calls-stats
```

Create virtual environment using only `virtualenv`:
```
virtualenv venv
source venv/bin/activate
```

Install libraries needed to run examples:
```
pip install -r requirements.txt
```

### Run example scripts and watch metrics stats

Provided previuos steps were performed (python installed, virtualenv created, dependencies pip-installed), it's easy to run example program:
```
python example-1-aiohttp-send-stats-basic.py
```

There should appear output in terminal:
```
(network-calls-stats) ➜  network-calls-stats git:(master) ✗ python example-1-aiohttp-send-stats-basic.py
Reported stats: aiohttp_request_exec_time=58, tags={'domain': 'www.python.org'}
Reported stats: aiohttp_request_exec_time=76, tags={'domain': 'www.mozilla.org'}
Reported stats: call_python_and_mozilla_using_aiohttp_exec_time=90, tags={}
Py response piece: <!doctype html>
<!--[if lt IE 7]>   <html class="no-js ie6 l... ,
Moz response piece: <!doctype html>

<html class="windows x86 no-js" lang="e...
```

To view reported request time stats on dashboard, need to setup datasource and panels in Grafana.

Navigate to grafana dashboard in browser (http://localhost:3000/). Add new data source:

[tutorial-images/setup-dashboard-add-new-source.png]
[tutorial-images/setup-dashboard-add-source-influx.png]
[tutorial-images/setup-dashboard-configure-source.png]

This data source should be used when configuring panels.

Let's create new dashboard for network stats, and add a panel to it.
Go to "Dashboards" in left side thin menu (icon looks like 4 bricks), pick "Manage", click on "New dashboard". Click "New panel" or "Add panel" in top right corner.
Pick "Edit" in dropdown next to new panel title.
Here's how to configure panel for Example 1:

[tutorial-images/example-1-request-time-dashboard-config-1.png]

One thing to notice is that panel shows Y axis values by default as 'short' type, but this can be changed in right side column - to use milliseconds:
[tutorial-images/example-1-request-time-dashboard-config-2.png]

Save panel, and real-time network call metrics should appear (if examples are still running).

More [documentation](https://grafana.com/docs/grafana/latest/panels/add-a-panel/) on  Grafana dashboards.

## Bonus: Telegraf histogram of request time

bonus: telegraf histogram ??