FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY application/* ./application/
COPY presentation/* ./presentation/
COPY database/* ./database/
EXPOSE 8080
CMD ["waitress-serve", "--listen=0.0.0.0:8080", "application.app:app"]