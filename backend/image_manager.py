"""
이미지 관리 시스템
- 이미지 서빙
- 썸네일 생성
- 이미지 최적화
"""

import os
from pathlib import Path
from PIL import Image
import io
from fastapi import HTTPException
from fastapi.responses import Response
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class ImageManager:
    def __init__(self, base_dir: str = ".."):
        self.base_dir = Path(base_dir)
        self.images_dir = self.base_dir / "img"
        
        # Docker 환경에서는 절대 경로 사용
        if not self.images_dir.exists():
            # 상위 디렉토리에서 img 폴더 찾기
            parent_dir = Path("/app").parent
            if (parent_dir / "img").exists():
                self.images_dir = parent_dir / "img"
            # 또는 /img 경로 시도
            elif Path("/img").exists():
                self.images_dir = Path("/img")
        
        self.thumbnails_dir = self.base_dir / "data" / "thumbnails"
        self.thumbnails_dir.mkdir(parents=True, exist_ok=True)
        
        logger.info(f"ImageManager initialized. Images dir: {self.images_dir}")
        logger.info(f"Images dir exists: {self.images_dir.exists()}")
    
    def get_image_path(self, filename: str) -> Path:
        """이미지 파일 경로 가져오기"""
        # 확장자 처리
        possible_extensions = ['.jpg', '.jpeg', '.png', '.JPG', '.JPEG', '.PNG']
        
        # 확장자가 있는 경우
        if any(filename.endswith(ext) for ext in possible_extensions):
            path = self.images_dir / filename
            if path.exists():
                return path
        
        # 확장자가 없는 경우 모든 확장자 시도
        base_name = filename.rsplit('.', 1)[0] if '.' in filename else filename
        for ext in possible_extensions:
            path = self.images_dir / f"{base_name}{ext}"
            if path.exists():
                return path
        
        return None
    
    def create_thumbnail(self, image_path: Path, size: tuple = (100, 100)) -> Path:
        """썸네일 생성"""
        try:
            thumbnail_path = self.thumbnails_dir / f"{image_path.stem}_thumb{image_path.suffix}"
            
            # 이미 존재하면 반환
            if thumbnail_path.exists():
                return thumbnail_path
            
            # 썸네일 생성
            with Image.open(image_path) as img:
                # RGB로 변환 (RGBA 등 처리)
                if img.mode != 'RGB':
                    img = img.convert('RGB')
                
                # 비율 유지하며 리사이즈
                img.thumbnail(size, Image.Resampling.LANCZOS)
                
                # 저장
                img.save(thumbnail_path, 'JPEG', quality=85, optimize=True)
            
            logger.info(f"Created thumbnail: {thumbnail_path.name}")
            return thumbnail_path
            
        except Exception as e:
            logger.error(f"Error creating thumbnail for {image_path}: {e}")
            return None
    
    def serve_image(self, filename: str, thumbnail: bool = False) -> Response:
        """이미지 서빙"""
        try:
            image_path = self.get_image_path(filename)
            
            if not image_path or not image_path.exists():
                raise HTTPException(status_code=404, detail="Image not found")
            
            # 썸네일 요청인 경우
            if thumbnail:
                thumbnail_path = self.create_thumbnail(image_path)
                if thumbnail_path and thumbnail_path.exists():
                    image_path = thumbnail_path
            
            # 이미지 읽기
            with open(image_path, "rb") as f:
                image_data = f.read()
            
            # Content-Type 결정
            content_type = "image/jpeg"
            if image_path.suffix.lower() in ['.png']:
                content_type = "image/png"
            
            return Response(
                content=image_data,
                media_type=content_type,
                headers={
                    "Cache-Control": "public, max-age=31536000",  # 1년 캐싱
                }
            )
            
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error serving image {filename}: {e}")
            raise HTTPException(status_code=500, detail="Internal server error")
    
    def get_all_images(self) -> list:
        """모든 이미지 목록 가져오기"""
        images = []
        
        if not self.images_dir.exists():
            return images
        
        for file_path in self.images_dir.glob("*"):
            if file_path.suffix.lower() in ['.jpg', '.jpeg', '.png']:
                images.append({
                    'filename': file_path.name,
                    'name': file_path.stem,
                    'size': file_path.stat().st_size,
                })
        
        return images
    
    def optimize_image(self, image_path: Path, max_size: tuple = (800, 800)) -> bool:
        """이미지 최적화"""
        try:
            with Image.open(image_path) as img:
                # RGB로 변환
                if img.mode != 'RGB':
                    img = img.convert('RGB')
                
                # 크기 조정
                if img.size[0] > max_size[0] or img.size[1] > max_size[1]:
                    img.thumbnail(max_size, Image.Resampling.LANCZOS)
                
                # 최적화하여 저장
                img.save(image_path, 'JPEG', quality=85, optimize=True)
            
            logger.info(f"Optimized image: {image_path.name}")
            return True
            
        except Exception as e:
            logger.error(f"Error optimizing image {image_path}: {e}")
            return False


# 전역 인스턴스
image_manager = ImageManager()
