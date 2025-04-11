# DOCX to DAISY 변환기

Microsoft Word 문서(DOCX)를 DAISY 형식으로 변환하는 파이썬 도구입니다.

## 기능

- DOCX 파일을 DAISY 2.02 형식으로 변환
- 문서의 제목과 단락 구조 보존
- 제목 수준(Heading 1-3) 지원
- DAISY 표준 준수 (DTBook, NCX, SMIL, OPF, Resources)
- 특수 마커를 통한 페이지, 각주, 사이드바 등 지원
- ZIP 압축 지원
- REST API 지원

## 설치

```bash
# 가상 환경 생성 (선택사항)
python -m venv venv
source venv/bin/activate  # Linux/Mac
# 또는
venv\Scripts\activate  # Windows

# 필요한 패키지 설치
pip install -e .
```

## 사용법

### API 사용법

API 서버 실행:
```bash
docx-to-daisy-api
```

API 엔드포인트:
- `GET /`: API 루트 경로
- `POST /convert`: DOCX 파일을 DAISY 형식으로 변환

API 사용 예시 (Python):
```python
import requests

url = "http://localhost:8000/convert/"
files = {"file": open("input.docx", "rb")}
params = {
    "title": "책 제목",
    "author": "저자 이름",
    "publisher": "출판사 이름",
    "language": "ko"
}

response = requests.post(url, files=files, params=params)

if response.status_code == 200:
    with open("output.zip", "wb") as f:
        f.write(response.content)
    print("변환 완료: output.zip")
else:
    print(f"오류: {response.json()}")
```

API 사용 예시 (cURL):
```bash
curl -X POST "http://localhost:8000/convert/" \
     -H "accept: application/json" \
     -H "Content-Type: multipart/form-data" \
     -F "file=@input.docx" \
     -F "title=책 제목" \
     -F "author=저자 이름" \
     -F "publisher=출판사 이름" \
     -F "language=ko" \
     --output output.zip
```

### API 파라미터

- `file`: 변환할 DOCX 파일 (필수)
- `title`: 책 제목 (선택 사항)
- `author`: 저자 (선택 사항)
- `publisher`: 출판사 (선택 사항)
- `language`: 언어 코드 (ISO 639-1) (기본값: ko)

### 지원하는 마커

DOCX 파일 내에서 다음과 같은 특수 마커를 사용할 수 있습니다:

- `$#숫자`: 페이지 번호 (예: `$#11`)
- `$note{내용}`: 각주
- `$sidebar{내용}`: 사이드바
- `$annotation{내용}`: 주석
- `$line{숫자}`: 줄 번호
- `$noteref{참조}`: 각주 참조
- `$prodnote{내용}`: 제작 노트

예시:
```
첫 번째 문단입니다.
$#1
두 번째 문단입니다.
$note{이것은 각주입니다.}
세 번째 문단입니다.
$#2
네 번째 문단입니다.
$sidebar{이것은 사이드바 내용입니다.}
```

## 생성되는 파일

- `dtbook.xml`: DAISY 텍스트 콘텐츠
- `book.opf`: DAISY 패키지 파일
- `navigation.ncx`: 네비게이션 컨트롤 파일
- `mo0.smil`: 텍스트 동기화 정보
- `resources.res`: 리소스 정보

## 제한사항

현재 버전은 다음 기능을 지원하지 않습니다:
- 오디오 콘텐츠
- 이미지
- 표
- 목록
- 수식

## 지원하는 DOCX 요소

- 제목 (Heading 1-3)
- 일반 문단
- 문서 메타데이터 (제목, 저자, 출판사, 언어)
- 특수 마커를 통한 페이지, 각주, 사이드바 등

## 라이선스

MIT License

## 기여하기

버그 리포트, 기능 제안, 풀 리퀘스트를 환영합니다.