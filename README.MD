## Загрузка изображений
### Mобильное приложение должно отправить POST-запрос на /upload-image/ с изображением в теле запроса. Файл должен быть отправлен как multipart/form-data
https://biggarik.ru/split_check/split_check
https://biggarik.ru/split_check/split_check/upload-image/

GET запрос: https://biggarik.ru/split_check/get_check?key=your_key
POST запрос: https://biggarik.ru/split_check/get_check с телом запроса {"key": "uid"}



cd c:\Users\big\Downloads\ngrok-v3-stable-windows-amd64\

ngrok http 8080


## Установка
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu


## Миграция
Создать новую миграцию:
alembic revision --autogenerate -m "add user profile table"
Применить миграцию:
alembic upgrade head


На проде активировать окружение
из директории /app/api

source venv/bin/activate

alembic -c src/migrations/alembic.ini revision --autogenerate -m "check name"

после этого ОБЯЗАТЕЛЬНО проверить, что он там наколбасил и только после этого применить миграцию

alembic -c src/migrations/alembic.ini upgrade head