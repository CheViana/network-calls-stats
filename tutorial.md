# Monitoring network calls in Python using TIG stack

[Intro wise words]


## Example 1: monitor aiohttp request time

Code...


If we change 'www.python.org' to 'www.python1.org', exceptions appear in terminal output, and exceptions stats is send to Telegraf:

    (network-calls-stats) ➜  network-calls-stats git:(master) ✗ python aiohttp-send-stats-basic.py
    Reported stats: aiohttp_request_exec_time=93, tags={'domain': 'www.mozilla.org'}
    Reported stats: aiohttp_request_exception=1, tags={'domain': 'www.python1.org', 'exception_class': 'ClientConnectorError'}
    ['Py response piece: ...Exception occured: Cannot conn... , Moz response piece: ...\n\n\n\n<!doctype html>\n\n<html cla...']
    Reported stats: aiohttp_request_exec_time=76, tags={'domain': 'www.mozilla.org'}


[tutorial-images/example-1-network-exceptions-on-dashboard.png]


## Running examples

### Prerequirements

Install Python3: https://docs.python-guide.org/starting/install3/ .
Make sure when you run
```
python --version
```
It prints out 'python3.' (could be 'python3.9', or 'python3.7', etc).

### Install and launch Telegraf, InfluxDB, Grafana

TODO

Run Telegraf, InfluxDB, Grafana (each in it's own shell tab):
```
telegraf -config telegraf.conf
```
Config file telegraf.conf is provided in examples repo.


```
influxd -config /usr/local/etc/influxdb.conf
```

```
cd grafana-7.1.0/
bin/grafana-server
```

Need to keep Telegraf, InfluxDB, Grafana running while running Python scripts to see results on dashboard.

### Examples repository

Checkout [repository]() with code examples and telegraf config.

### Python dependencies

It's best to create virtual environment to keep dependencies of project isolated from system Python packages, and dependencies of other projects. For that, I suggest to use virtualenv: https://virtualenv.pypa.io/en/latest/installation.html and virtualenvwrapper: https://virtualenvwrapper.readthedocs.io/en/latest/install.html. Need to install these tools if you don't have them installed already.

Create virtual environment using `virtualenvwrapper`:
```
mkvirtualenv network-calls-stats
```

Create virtual environment using only `virtualenv`:
```
virtualenv venv
source venv/bin/activate
```

Install project dependencies:
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
Create new dashboard and configure panel for Example 1:

[tutorial-images/example-1-request-time-dashboard-config-1.png]
[tutorial-images/example-1-request-time-dashboard-config-2.png]

Save panel, and real-time network call metrics should appear.


### Bonus: Telegraf histogram of request time

bonus: telegraf histogram ??