# Monitoring network calls in Python using TIG stack

[Intro wise words]

## Example 1: monitor `aiohttp` request time

I'm going to describe in detail code example that does following:
- executes two asyncronous HTTP requests
- hooks into `aiohttp` signals for request execution
- reports request time and request exceptions to Telegraf

Here's execution time results on dashboard:
[tutorial-images/example-1-request-time-results.png]

Full code of Example 1 can be found [here](https://github.com/CheViana/network-calls-stats/blob/master/example-1-aiohttp-send-stats-basic.py).

See chapter 'Running code examples' below on how to run example code and setup monitoring infrastructure.

### The tale of two HTTP requests

Let's start with function `call_python_and_mozilla` that executes two asyncronous HTTP requests and prints out bits of response content received:

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
async def call_python_and_mozilla():
        py_response, moz_response = await asyncio.gather(
            get_response_text('https://www.python.org/'),
            get_response_text('https://www.mozilla.org/en-US/')
        )
        return (
            f'Py response piece: ...{py_response[:30]}... , '
            f'Moz response piece: ...{moz_response[:30]}...'
        )
```

Code uses `aiohttp` library ([docs](https://docs.aiohttp.org/en/stable/client.html)). Basic usage to get text content from URL is following:
```
async with ClientSession() as session:
    async with session.get(url) as response:
        return await response.text()
```

Which is basically what happens in `get_response_text`. `get_response_text` also calls `response.raise_for_status()` which raises exception when response status code is error code or timeout occurs (`aiohttp` [docs on exceptions](https://docs.aiohttp.org/en/stable/client_reference.html#client-exceptions)). Exception is silenced in `get_response_text`, so `get_response_text` always returns `str`, either with response content or with exception message.

`call_python_and_mozilla` takes care of callings 2 URLs using `asyncio.gather` (if it's all very new to you, suggest to [read about tasks and coroutines more](https://python.readthedocs.io/en/latest/library/asyncio-task.html)). Execution order is following:

first request is sent --> second request is sent --> wait for either one of requests to complete --> first response is received --> second response is received

Total execution time is approximately the time of the longest request out of these two. You're probably aware that this is called non-blocking IO: IO operation frees execution thread, until it needs it again, instead of blocking.

Traditional, not asyncronous, blocking IO, has following execution order:

first request is sent --> wait for first request to complete --> first response is received --> second request is sent --> wait for second request to complete --> second response is received

And total execution time is approximately the sum of both requests execution time. For positive integers, it's always true that `A + B > MAX(A, B)` hence asyncronous execution takes less time than syncronous. Provided unlimited CPU was made available to Python program in both cases, async and sync.

On panel that shows both requests time from Example 1, and their total execution time, it's possible to notice that total execution time `call_python_and_mozilla_exec_time` almost matches the longer-executing request time:

[tutorial-images/example-1-requests-and-total-time.png]

`@profile` decorator takes care of reporting total execution time of function `call_python_and_mozilla_exec_time`. Next we're going to look at how execution time of each `aiohttp` request is reported.


### `aiohttp` requests signals

`aiohttp` provides a way to execute custom function when HTTP request execution progresses through lifecycle stages: before request is sent, when connection is established, after response chunk is received, etc ([full list](https://docs.aiohttp.org/en/stable/tracing_reference.html)).

For that, special kwarg is passed to `aiohttp.ClientSession`:
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

`Profiler` is subclass of `aiohttp.TraceConfig`, and in constructor attaches functions that are going to be executed when request starts (`on_request_start`), when it ends (`on_request_end`), and when request exception is encountered (`on_request_exception`):
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
It is recommended to use event loop’s internal monotonic clock to compute timedelta rather than `time.now()` or `time.perf_counter()`.

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

`params` argument in `on_request_end` is `aiohttp.TraceRequestEndParams` and as such has `url` property. `url` property is of `yarl.URL` type. `params.url.raw_host` returns domain of URL which was requested. Domain is sent as tag and it's possible to plot separate lines for request execution time for requests to different domains. 

### Sending stats

`aiohttp` request lifecycle hooks, as well as `profile` decorator, send stats to Telegraf using function `send_stats`.
I have [another post](https://dev.to/cheviana/reporting-measurements-from-python-code-in-real-time-4g5) that describes in more details ways to send stats from Python program to Telegraf.

In Example 1 code special processing of reported values takes place: replacing some special chars with '-', as ':' in metric name is known to make Telegraf reject metric readings (see function `prepare_str_for_telegraf`).

### `profile` decorator

Some time ago I wrote a little piece of code which is decorator suitable for any function: async, sync, method of class or pure function. Here it is adapted to profile function that is decorated:

```
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
```

It could be used as:
```
    @profile
    def something_that_takes_little_time(...):
        ...

    @profile(metric_name='my_exec_time')
    async def something_that_takes_more_time(...):
        ...


    class Bingo:
        @profile
        def play(self, ...):
            ...

        @profile
        async def pay(self, ...):
            ...
```

In Example 1 `profile` decorator is used to profile total execition time of function `call_python_and_mozilla`.

### Need more exceptions

If we change 'www.python.org' to 'www.python1.org' in function `call_python_and_mozilla`, exceptions appear in terminal output, and exception metrics are sent to Telegraf:

    (network-calls-stats) ➜  network-calls-stats git:(master) ✗ python aiohttp-send-stats-basic.py
    Reported stats: aiohttp_request_exec_time=93, tags={'domain': 'www.mozilla.org'}
    Reported stats: aiohttp_request_exception=1, tags={'domain': 'www.python1.org', 'exception_class': 'ClientConnectorError'}
    ['Py response piece: ...Exception occured: Cannot conn... , Moz response piece: ...\n\n\n\n<!doctype html>\n\n<html cla...']
    Reported stats: aiohttp_request_exec_time=76, tags={'domain': 'www.mozilla.org'}


Configure separate Grafana panel to see exceptions on dashboard:
[tutorial-images/example-1-network-exceptions-on-dashboard.png]

Exception class is sent as tag along with metric value. This gives us ability to plot different lines in panel for exceptions of different classes. To achieve this, pick 'group by - tag(exception_class)' when editing request exceptions query in Grafana panel.


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
Reported stats: aiohttp_request_exec_time=66, tags={'domain': 'www.python.org'}
Reported stats: aiohttp_request_exec_time=101, tags={'domain': 'www.mozilla.org'}
['Py response piece: ...<!doctype html>\n<!--[if lt IE ... , Moz response piece: ...\n\n\n\n<!doctype html>\n\n<html cla...']
Reported stats: aiohttp_request_exec_time=34, tags={'domain': 'www.python.org'}
Reported stats: aiohttp_request_exec_time=65, tags={'domain': 'www.mozilla.org'}
['Py response piece: ...<!doctype html>\n<!--[if lt IE ... , Moz response piece: ...\n\n\n\n<!doctype html>\n\n<html cla...']
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