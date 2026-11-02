# Mac 本地隔离启动

执行 `sh run_local.sh`。脚本使用 Python 3.11 创建 `.venv-local`，在同一解释器下安装依赖、检查依赖并启动 `dev_local.py`。可用 `LOGISTICS_PYTHON=/绝对路径/python3.11 sh run_local.sh` 指定解释器；原失效的 `.venv` 保留。

依赖以 requirements.txt 为唯一来源，requirements-test.txt 引用它。Flask-WTF==1.2.2 已声明，Python 模块名是 flask_wtf；WTForms 固定为与 Flask-Admin 1.6.1 经测试兼容的 3.1.2。

测试环境安装成功不代表用户终端中的另一个 Python 环境也已经安装依赖。之前测试使用 /tmp 下专用环境；单独执行 python dev_local.py 可能使用其他解释器。因此统一通过脚本启动。

地址 http://127.0.0.1:5055/login。虚构管理员 local-admin / local-test-only；只读用户 local-reader / local-read-only。数据库每次启动均为临时库，跳过 .env，禁止外部网络。不执行旧 run.sh、初始化、重置或刷新脚本。

回归命令：`.venv-local/bin/python -B -m unittest discover -s tests -p 'test_*.py' -v`。

新增业务模块中的 Flask、Flask-Login、Flask-Admin、Flask-WTF、Requests、SQLAlchemy 均已声明，其他导入为标准库或项目模块。旧 auto_refresh.py 仍依赖未声明的 schedule，本次不执行或验证该旧调度程序；本地 Web 启动不依赖它。

若 5055 已占用，用 `LOGISTICS_LOCAL_PORT=5056 sh run_local.sh` 指定其他端口；不要结束未知进程。
