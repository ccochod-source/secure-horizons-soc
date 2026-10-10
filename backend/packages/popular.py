"""Packages les plus répandus, référence de la détection de typosquatting."""

from __future__ import annotations

PYPI = frozenset("""
requests urllib3 boto3 botocore setuptools certifi charset-normalizer idna typing-extensions
python-dateutil packaging six numpy pandas pyyaml s3transfer cryptography pip wheel jmespath
attrs click pydantic pydantic-core platformdirs fsspec jinja2 markupsafe pytz protobuf cffi
pycparser rsa pyasn1 awscli importlib-metadata zipp filelock virtualenv tomli colorama pluggy
pytest iniconfig psutil sqlalchemy greenlet aiohttp yarl multidict frozenlist aiosignal pyjwt
google-api-core googleapis-common-protos grpcio pyparsing wrapt scipy pillow openpyxl httpx
httpcore anyio sniffio h11 flask werkzeug itsdangerous django fastapi starlette uvicorn
gunicorn scikit-learn matplotlib tqdm beautifulsoup4 soupsieve lxml redis celery paramiko
psycopg2 psycopg2-binary psycopg pymysql pymongo docker kubernetes openai anthropic langchain
langchain-core langchain-openai langgraph tiktoken tokenizers transformers torch tensorflow
keras huggingface-hub regex rich pygments black isort flake8 mypy ruff tox coverage selenium
playwright python-dotenv supabase mcp tenacity jsonschema referencing decorator tabulate
networkx pyarrow dill cloudpickle joblib threadpoolctl oauthlib requests-oauthlib bcrypt
pynacl pyopenssl websockets websocket-client markdown alembic mako sympy nltk spacy
""".split())

NPM = frozenset("""
lodash react react-dom chalk commander express debug axios tslib typescript moment uuid
async fs-extra glob minimist yargs semver request rxjs webpack eslint prettier jest mocha
vue next nuxt angular jquery underscore bluebird classnames prop-types dotenv body-parser
cors mkdirp rimraf inquirer colors ws socket.io mongoose mongodb mysql pg redis ioredis
node-fetch cross-env nodemon babel-core core-js regenerator-runtime webpack-cli rollup vite
esbuild postcss autoprefixer tailwindcss sass less styled-components redux react-redux
react-router react-router-dom zod yup joi ajv handlebars ejs pug marked cheerio puppeteer
playwright jsonwebtoken bcrypt bcryptjs passport helmet morgan winston pino dayjs date-fns
luxon ramda immutable immer qs form-data multer sharp nanoid shelljs execa ora open
supabase openai langchain electron husky lint-staged ts-node tsx vitest cypress
""".split())

BY_ECOSYSTEM = {"pypi": PYPI, "npm": NPM}
