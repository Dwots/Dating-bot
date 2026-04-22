import boto3
from botocore.exceptions import ClientError
import io
import uuid


class MinioClient:
    """
    Как работает MinIO / S3:

    Бакет (bucket) — это как папка верхнего уровня
    Объект (object) — файл внутри бакета, у него есть ключ (путь)

    Пример:
      бакет: "profiles"
      ключ:  "photos/123456789/a1b2c3.jpg"
      
    boto3 — официальный AWS SDK для Python, работает с любым S3-совместимым хранилищем
    endpoint_url — говорим boto3 что наш "S3" это MinIO, а не настоящий AWS
    """

    def __init__(self, endpoint: str, access_key: str, secret_key: str, bucket: str):
        self.bucket = bucket
        # boto3 синхронный — будем запускать в executor чтобы не блокировать asyncio
        self.client = boto3.client(
            "s3",
            endpoint_url=f"http://{endpoint}",
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            # отключаем проверку региона — MinIO не требует его
            region_name="us-east-1",
        )
        self._ensure_bucket()

    def _ensure_bucket(self):
        """Создаём бакет если его ещё нет"""
        try:
            self.client.head_bucket(Bucket=self.bucket)
        except ClientError:
            self.client.create_bucket(Bucket=self.bucket)

    def upload_photo(self, file_bytes: bytes, user_id: int) -> str:
        """
        Загружаем фото в MinIO
        Возвращаем s3_key — путь по которому потом достанем файл

        user_id нужен чтобы организовать файлы по папкам:
          photos/123456/uuid.jpg
          photos/789012/uuid.jpg
        """
        # uuid гарантирует уникальность имени файла
        file_name = f"{uuid.uuid4().hex}.jpg"
        s3_key = f"photos/{user_id}/{file_name}"

        self.client.upload_fileobj(
            io.BytesIO(file_bytes),
            self.bucket,
            s3_key,
            ExtraArgs={"ContentType": "image/jpeg"},
        )
        return s3_key

    def get_photo_bytes(self, s3_key: str) -> bytes:
        """
        Скачиваем фото из MinIO по ключу
        Возвращаем байты — aiogram умеет отправлять фото из байтов
        """
        response = self.client.get_object(Bucket=self.bucket, Key=s3_key)
        return response["Body"].read()

    def delete_photo(self, s3_key: str):
        """Удаляем фото из MinIO"""
        self.client.delete_object(Bucket=self.bucket, Key=s3_key)