FROM python:3.12.8

# poetryのPATHを$PATHに追加
ENV PATH /root/.local/bin:$PATH

WORKDIR /track-job-hackathon-0302

RUN apt-get update \
    && curl -sSL https://install.python-poetry.org | python3 -

# コンテナ実行後に行いたいコマンドを記述する FastAPIの場合の例は下記
CMD ["bash", "-c", "poetry install && poetry run streamlit run ./src/track-job-hackathon-0302/main.py"]
