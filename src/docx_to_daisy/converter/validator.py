import os
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional
from lxml import etree
import zipfile

logger = logging.getLogger(__name__)

class ValidationError:
    """검증 오류 정보를 담는 클래스"""
    def __init__(self, category: str, message: str, details: Optional[Dict] = None, severity: str = "error"):
        self.category = category
        self.message = message
        self.details = details or {}
        self.severity = severity  # "error" 또는 "warning"

class ValidationResult:
    """검증 결과를 담는 클래스"""
    def __init__(self):
        self.is_valid = True
        self.errors: List[ValidationError] = []
        self.warnings: List[ValidationError] = []
        self.summary: Dict[str, Any] = {}
    
    def add_error(self, category: str, message: str, details: Optional[Dict] = None):
        """심각한 오류 추가"""
        error = ValidationError(category, message, details, "error")
        self.errors.append(error)
        self.is_valid = False
        logger.error(f"[검증 오류] {category}: {message}")
    
    def add_warning(self, category: str, message: str, details: Optional[Dict] = None):
        """경고 추가"""
        warning = ValidationError(category, message, details, "warning")
        self.warnings.append(warning)
        logger.warning(f"[검증 경고] {category}: {message}")
    
    def get_summary(self) -> Dict[str, Any]:
        """검증 결과 요약 반환"""
        return {
            "is_valid": self.is_valid,
            "error_count": len(self.errors),
            "warning_count": len(self.warnings),
            "errors": [{"category": e.category, "message": e.message, "details": e.details} for e in self.errors],
            "warnings": [{"category": w.category, "message": w.message, "details": w.details} for w in self.warnings]
        }

class DaisyValidator:
    """DAISY 포맷 검증기"""
    
    def __init__(self, output_dir: str):
        self.output_dir = Path(output_dir)
        self.result = ValidationResult()
        
        # 필수 파일 목록
        self.required_files = [
            "dtbook.xml",
            "dtbook.opf", 
            "dtbook.smil",
            "dtbook.ncx",
            "dtbook.res"
        ]
    
    def validate_all(self) -> ValidationResult:
        """모든 검증을 수행"""
        logger.info("DAISY 파일 검증 시작...")
        
        try:
            # 1. 파일 구조 검증
            self.validate_file_structure()
            
            # 2. XML 스키마 검증
            self.validate_xml_schemas()
            
            # 3. 콘텐츠 무결성 검증
            self.validate_content_integrity()
            
            # 4. 접근성 검증
            self.validate_accessibility()
            
            # 검증 결과 요약 생성
            self.result.summary = self.result.get_summary()
            
            if self.result.is_valid:
                logger.info("DAISY 파일 검증 완료: 모든 검증을 통과했습니다.")
            else:
                logger.error(f"DAISY 파일 검증 실패: {len(self.result.errors)}개의 오류 발견")
            
            return self.result
            
        except Exception as e:
            logger.error(f"검증 중 예상치 못한 오류 발생: {str(e)}")
            self.result.add_error("system", f"검증 시스템 오류: {str(e)}")
            return self.result
    
    def validate_file_structure(self):
        """파일 구조 검증"""
        logger.info("파일 구조 검증 중...")
        
        # 필수 파일 존재 확인
        for filename in self.required_files:
            file_path = self.output_dir / filename
            if not file_path.exists():
                self.result.add_error("file_structure", f"필수 파일이 없습니다: {filename}")
            elif file_path.stat().st_size == 0:
                self.result.add_error("file_structure", f"파일이 비어있습니다: {filename}")
        
        # 이미지 파일 존재 확인 (OPF에서 참조하는 이미지들)
        try:
            opf_path = self.output_dir / "dtbook.opf"
            if opf_path.exists():
                self.validate_image_references(opf_path)
        except Exception as e:
            self.result.add_warning("file_structure", f"이미지 참조 검증 중 오류: {str(e)}")
    
    def validate_xml_schemas(self):
        """XML 스키마 검증"""
        logger.info("XML 스키마 검증 중...")
        
        # DTBook XML 검증
        dtbook_path = self.output_dir / "dtbook.xml"
        if dtbook_path.exists():
            self.validate_dtbook_xml(dtbook_path)
        
        # OPF 파일 검증
        opf_path = self.output_dir / "dtbook.opf"
        if opf_path.exists():
            self.validate_opf_xml(opf_path)
        
        # SMIL 파일 검증
        smil_path = self.output_dir / "dtbook.smil"
        if smil_path.exists():
            self.validate_smil_xml(smil_path)
        
        # NCX 파일 검증
        ncx_path = self.output_dir / "dtbook.ncx"
        if ncx_path.exists():
            self.validate_ncx_xml(ncx_path)
    
    def validate_content_integrity(self):
        """콘텐츠 무결성 검증"""
        logger.info("콘텐츠 무결성 검증 중...")
        
        try:
            # DTBook과 SMIL 간의 ID 참조 검증
            self.validate_id_references()
            
            # 메타데이터 일관성 검증
            self.validate_metadata_consistency()
            
        except Exception as e:
            self.result.add_warning("content_integrity", f"콘텐츠 무결성 검증 중 오류: {str(e)}")
    
    def validate_accessibility(self):
        """접근성 검증"""
        logger.info("접근성 검증 중...")
        
        try:
            # 이미지 대체 텍스트 검증
            self.validate_image_alt_text()
            
            # 제목 구조 검증
            self.validate_heading_structure()
            
        except Exception as e:
            self.result.add_warning("accessibility", f"접근성 검증 중 오류: {str(e)}")
    
    def validate_image_references(self, opf_path: Path):
        """OPF에서 참조하는 이미지 파일 존재 확인"""
        try:
            tree = etree.parse(str(opf_path))
            root = tree.getroot()
            
            # OPF 네임스페이스
            opf_ns = "http://openebook.org/namespaces/oeb-package/1.0/"
            
            # manifest에서 이미지 항목 찾기
            manifest = root.find(f"{{{opf_ns}}}manifest")
            if manifest is not None:
                for item in manifest.findall(f"{{{opf_ns}}}item"):
                    href = item.get("href")
                    media_type = item.get("media-type", "")
                    
                    if href and media_type.startswith("image/"):
                        image_path = self.output_dir / href
                        if not image_path.exists():
                            self.result.add_error("file_structure", f"OPF에서 참조하는 이미지 파일이 없습니다: {href}")
                        elif image_path.stat().st_size == 0:
                            self.result.add_error("file_structure", f"이미지 파일이 비어있습니다: {href}")
                            
        except Exception as e:
            self.result.add_warning("file_structure", f"이미지 참조 검증 중 오류: {str(e)}")
    
    def validate_dtbook_xml(self, dtbook_path: Path):
        """DTBook XML 검증"""
        try:
            tree = etree.parse(str(dtbook_path))
            root = tree.getroot()
            
            # 기본 구조 확인
            if root.tag != "{http://www.daisy.org/z3986/2005/dtbook/}dtbook":
                self.result.add_error("xml_schema", "DTBook XML의 루트 요소가 올바르지 않습니다")
            
            # 필수 요소 확인
            head = root.find("{http://www.daisy.org/z3986/2005/dtbook/}head")
            book = root.find("{http://www.daisy.org/z3986/2005/dtbook/}book")
            
            if head is None:
                self.result.add_error("xml_schema", "DTBook XML에 head 요소가 없습니다")
            if book is None:
                self.result.add_error("xml_schema", "DTBook XML에 book 요소가 없습니다")
                
        except etree.XMLSyntaxError as e:
            self.result.add_error("xml_schema", f"DTBook XML 구문 오류: {str(e)}")
        except Exception as e:
            self.result.add_warning("xml_schema", f"DTBook XML 검증 중 오류: {str(e)}")
    
    def validate_opf_xml(self, opf_path: Path):
        """OPF XML 검증"""
        try:
            tree = etree.parse(str(opf_path))
            root = tree.getroot()
            
            # 네임스페이스 고려하여 기본 구조 확인
            try:
                localname = etree.QName(root.tag).localname
            except Exception:
                localname = root.tag
            if localname != "package":
                self.result.add_error("xml_schema", "OPF XML의 루트 요소가 올바르지 않습니다")
            
            # 필수 요소 확인 (네임스페이스 포함)
            opf_ns = "http://openebook.org/namespaces/oeb-package/1.0/"
            metadata = root.find(f"{{{opf_ns}}}metadata")
            manifest = root.find(f"{{{opf_ns}}}manifest")
            spine = root.find(f"{{{opf_ns}}}spine")
            
            if metadata is None:
                self.result.add_error("xml_schema", "OPF XML에 metadata 요소가 없습니다")
            if manifest is None:
                self.result.add_error("xml_schema", "OPF XML에 manifest 요소가 없습니다")
            if spine is None:
                self.result.add_error("xml_schema", "OPF XML에 spine 요소가 없습니다")
                
        except etree.XMLSyntaxError as e:
            self.result.add_error("xml_schema", f"OPF XML 구문 오류: {str(e)}")
        except Exception as e:
            self.result.add_warning("xml_schema", f"OPF XML 검증 중 오류: {str(e)}")
    
    def validate_smil_xml(self, smil_path: Path):
        """SMIL XML 검증"""
        try:
            tree = etree.parse(str(smil_path))
            root = tree.getroot()
            
            # 기본 구조 확인
            if root.tag != "{http://www.w3.org/2001/SMIL20/}smil":
                self.result.add_error("xml_schema", "SMIL XML의 루트 요소가 올바르지 않습니다")
            
            # 필수 요소 확인
            head = root.find("{http://www.w3.org/2001/SMIL20/}head")
            body = root.find("{http://www.w3.org/2001/SMIL20/}body")
            
            if head is None:
                self.result.add_error("xml_schema", "SMIL XML에 head 요소가 없습니다")
            if body is None:
                self.result.add_error("xml_schema", "SMIL XML에 body 요소가 없습니다")
                
        except etree.XMLSyntaxError as e:
            self.result.add_error("xml_schema", f"SMIL XML 구문 오류: {str(e)}")
        except Exception as e:
            self.result.add_warning("xml_schema", f"SMIL XML 검증 중 오류: {str(e)}")
    
    def validate_ncx_xml(self, ncx_path: Path):
        """NCX XML 검증"""
        try:
            tree = etree.parse(str(ncx_path))
            root = tree.getroot()
            
            # NCX 네임스페이스
            ncx_ns = "http://www.daisy.org/z3986/2005/ncx/"
            
            # 기본 구조 확인
            if root.tag != f"{{{ncx_ns}}}ncx":
                self.result.add_error("xml_schema", "NCX XML의 루트 요소가 올바르지 않습니다")
            
            # 필수 요소 확인
            head = root.find(f"{{{ncx_ns}}}head")
            nav_map = root.find(f"{{{ncx_ns}}}navMap")
            
            if head is None:
                self.result.add_error("xml_schema", "NCX XML에 head 요소가 없습니다")
            if nav_map is None:
                self.result.add_error("xml_schema", "NCX XML에 navMap 요소가 없습니다")
                
        except etree.XMLSyntaxError as e:
            self.result.add_error("xml_schema", f"NCX XML 구문 오류: {str(e)}")
        except Exception as e:
            self.result.add_warning("xml_schema", f"NCX XML 검증 중 오류: {str(e)}")
    
    def validate_id_references(self):
        """DTBook과 SMIL 간의 ID 참조 검증"""
        try:
            dtbook_path = self.output_dir / "dtbook.xml"
            smil_path = self.output_dir / "dtbook.smil"
            
            if not dtbook_path.exists() or not smil_path.exists():
                return
            
            # DTBook의 ID 수집
            dtbook_tree = etree.parse(str(dtbook_path))
            dtbook_ids = set()
            for elem in dtbook_tree.iter():
                elem_id = elem.get("id")
                if elem_id:
                    dtbook_ids.add(elem_id)
            
            # SMIL의 src 참조 검증
            smil_tree = etree.parse(str(smil_path))
            smil_ns = "http://www.w3.org/2001/SMIL20/"
            
            for text_elem in smil_tree.findall(f".//{{{smil_ns}}}text"):
                src = text_elem.get("src")
                if src and "#" in src:
                    ref_id = src.split("#")[1]
                    if ref_id not in dtbook_ids:
                        self.result.add_warning("content_integrity", f"SMIL에서 참조하는 ID가 DTBook에 없습니다: {ref_id}")
                        
        except Exception as e:
            self.result.add_warning("content_integrity", f"ID 참조 검증 중 오류: {str(e)}")
    
    def validate_metadata_consistency(self):
        """메타데이터 일관성 검증"""
        try:
            # DTBook과 OPF의 메타데이터 비교
            dtbook_path = self.output_dir / "dtbook.xml"
            opf_path = self.output_dir / "dtbook.opf"
            
            if not dtbook_path.exists() or not opf_path.exists():
                return
            
            # DTBook 메타데이터 추출
            dtbook_tree = etree.parse(str(dtbook_path))
            dtbook_title = None
            dtbook_author = None
            dtbook_ns = "http://www.daisy.org/z3986/2005/dtbook/"
            for meta in dtbook_tree.findall(f".//{{{dtbook_ns}}}meta"):
                name = meta.get("name")
                content = meta.get("content")
                if name == "dc:Title":
                    dtbook_title = content
                elif name == "dc:Creator":
                    dtbook_author = content
            
            # OPF 메타데이터 추출
            opf_tree = etree.parse(str(opf_path))
            opf_ns = "http://openebook.org/namespaces/oeb-package/1.0/"
            dc_ns = "http://purl.org/dc/elements/1.1/"
            
            opf_title = None
            opf_author = None
            
            dc_metadata = opf_tree.find(f".//{{{opf_ns}}}dc-metadata")
            if dc_metadata is not None:
                title_elem = dc_metadata.find(f"{{{dc_ns}}}Title")
                if title_elem is not None:
                    opf_title = title_elem.text
                
                creator_elem = dc_metadata.find(f"{{{dc_ns}}}Creator")
                if creator_elem is not None:
                    opf_author = creator_elem.text
            
            # 메타데이터 일치 확인
            if dtbook_title and opf_title and dtbook_title != opf_title:
                self.result.add_warning("metadata_consistency", "DTBook과 OPF의 제목이 일치하지 않습니다")
            
            if dtbook_author and opf_author and dtbook_author != opf_author:
                self.result.add_warning("metadata_consistency", "DTBook과 OPF의 저자가 일치하지 않습니다")
                
        except Exception as e:
            self.result.add_warning("metadata_consistency", f"메타데이터 일관성 검증 중 오류: {str(e)}")
    
    def validate_image_alt_text(self):
        """이미지 대체 텍스트 검증"""
        try:
            dtbook_path = self.output_dir / "dtbook.xml"
            if not dtbook_path.exists():
                return
            
            dtbook_tree = etree.parse(str(dtbook_path))
            dtbook_ns = "http://www.daisy.org/z3986/2005/dtbook/"
            
            # 이미지 요소 찾기
            for img in dtbook_tree.findall(f".//{{{dtbook_ns}}}img"):
                alt = img.get("alt")
                if not alt or alt.strip() == "":
                    self.result.add_warning("accessibility", "이미지에 대체 텍스트가 없습니다")
                    
        except Exception as e:
            self.result.add_warning("accessibility", f"이미지 대체 텍스트 검증 중 오류: {str(e)}")
    
    def validate_heading_structure(self):
        """제목 구조 검증"""
        try:
            dtbook_path = self.output_dir / "dtbook.xml"
            if not dtbook_path.exists():
                return
            
            dtbook_tree = etree.parse(str(dtbook_path))
            dtbook_ns = "http://www.daisy.org/z3986/2005/dtbook/"
            
            # 제목 요소들 찾기
            headings = []
            for i in range(1, 7):  # h1 ~ h6
                for h in dtbook_tree.findall(f".//{{{dtbook_ns}}}h{i}"):
                    headings.append((i, h))
            
            # 제목 계층 구조 검증
            if not headings:
                self.result.add_warning("accessibility", "문서에 제목이 없습니다")
            else:
                # h1이 있는지 확인
                h1_count = len([h for level, h in headings if level == 1])
                if h1_count == 0:
                    self.result.add_warning("accessibility", "최상위 제목(h1)이 없습니다")
                elif h1_count > 1:
                    self.result.add_warning("accessibility", "최상위 제목(h1)이 여러 개 있습니다")
                    
        except Exception as e:
            self.result.add_warning("accessibility", f"제목 구조 검증 중 오류: {str(e)}")
