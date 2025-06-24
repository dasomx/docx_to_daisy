"""DAISY 변환을 위한 예약어(마커) 처리 모듈"""

import re
from dataclasses import dataclass
from typing import List, Optional, Tuple
import xml.etree.ElementTree as ET


@dataclass
class Marker:
    """DAISY 마커 정보를 담는 클래스"""
    type: str  # 마커 타입 (예: page, note, sidebar 등)
    value: str  # 마커 값 (예: 페이지 번호)
    original: str  # 원본 마커 텍스트


class MarkerProcessor:
    """DAISY 마커 처리기"""

    # 마커 패턴 정의
    MARKERS = {
        'page': r'\$#(\d+(?:[.-]\d+)?)',  # 페이지 마커: $#11, $#3-1, $#8.1
        'note': r'\$note\{([^}]+)\}',  # 각주 마커: $note{각주 내용}
        'sidebar': r'\$sidebar\{([^}]+)\}',  # 사이드바 마커: $sidebar{사이드바 내용}
        'annotation': r'\$annotation\{([^}]+)\}',  # 주석 마커: $annotation{주석 내용}
        'linenum': r'\$line\{(\d+)\}',  # 줄 번호 마커: $line{123}
        'noteref': r'\$noteref\{([^}]+)\}',  # 각주 참조 마커: $noteref{1}
        'prodnote': r'\$prodnote\{([^}]+)\}',  # 제작 노트 마커: $prodnote{제작 노트 내용}
    }

    @classmethod
    def find_markers(cls, text: str) -> List[Marker]:
        """텍스트에서 모든 마커를 찾아 반환

        Args:
            text (str): 검사할 텍스트

        Returns:
            List[Marker]: 발견된 마커 목록
        """
        markers = []
        for marker_type, pattern in cls.MARKERS.items():
            for match in re.finditer(pattern, text):
                markers.append(Marker(
                    type=marker_type,
                    value=match.group(1),
                    original=match.group(0)
                ))
        return sorted(markers, key=lambda m: text.index(m.original))

    @classmethod
    def process_text(cls, text: str) -> Tuple[str, List[Marker]]:
        """텍스트를 처리하고 마커를 추출

        Args:
            text (str): 처리할 텍스트

        Returns:
            Tuple[str, List[Marker]]: (처리된 텍스트, 마커 목록)
        """
        markers = cls.find_markers(text)
        processed_text = text

        # 마커를 제거하고 필요한 경우 대체 텍스트 삽입
        for marker in reversed(markers):  # 역순으로 처리하여 위치 변화 방지
            if marker.type == 'page':
                # 페이지 마커는 완전히 제거
                processed_text = processed_text.replace(marker.original, '')
            elif marker.type in ['note', 'sidebar', 'prodnote']:
                # 이러한 마커들은 내용을 유지
                processed_text = processed_text.replace(
                    marker.original, marker.value)
            else:
                # 기타 마커는 제거
                processed_text = processed_text.replace(marker.original, '')

        return processed_text, markers

    @classmethod
    def create_dtbook_element(cls, marker: Marker, dtbook_xml):
        """마커에 해당하는 DTBook 요소 정보 생성

        Args:
            marker (Marker): 처리할 마커
            dtbook_xml (ElementTree): 이미 생성된 DTBook XML 트리

        Returns:
            Optional[Element]: 생성된 DTBook 요소 또는 None
        """
        if marker.type == 'page':
            # Add a pagenum tag to the DTBook xml, if the dtbook_xml is already created
            if dtbook_xml.find(".//{http://www.daisy.org/z3986/2005/dtbook/}pagenum[@id='page_{0}_{0}']".format(marker.value)) is None:
                pagenum = ET.Element("{http://www.daisy.org/z3986/2005/dtbook/}pagenum")
                pagenum.set("id", "page_{0}_{0}".format(marker.value))
                pagenum.set("page", "normal")
                pagenum.set("smilref", "dtbook.smil#smil_par_page_{0}_{0}".format(marker.value))
                pagenum.text = str(marker.value)
                return pagenum
        elif marker.type == 'note':
            return {
                'tag': 'note',
                'attrs': {'id': f'note_{marker.value}'},
                'text': marker.value
            }
        elif marker.type == 'sidebar':
            return {
                'tag': 'sidebar',
                'attrs': {'id': f'sidebar_{marker.value}'},
                'text': marker.value
            }
        elif marker.type == 'annotation':
            return {
                'tag': 'annotation',
                'attrs': {'id': f'annot_{marker.value}'},
                'text': marker.value
            }
        elif marker.type == 'prodnote':
            return {
                'tag': 'prodnote',
                'attrs': {'id': f'prodnote_{marker.value}'},
                'text': marker.value
            }
        return None

    @classmethod
    def create_smil_element(cls, marker: Marker, dtbook_path):
        """마커에 해당하는 SMIL 요소 정보 생성

        Args:
            marker (Marker): 처리할 마커
            dtbook_path (str): DTBook 파일의 경로

        Returns:
            Optional[dict]: SMIL 요소 정보 또는 None
        """
        if marker.type == 'page':
            return {
                'seq_class': 'pagenum',
                'par_class': 'pagenum',
                'text_src': f'dtbook.xml#page_{marker.value}_{marker.value}'
            }
        elif marker.type == 'note':
            return {
                'seq_class': 'note',
                'par_class': 'note',
                'text_src': f'dtbook.xml#note_{marker.value}'
            }
        elif marker.type == 'sidebar':
            return {
                'seq_class': 'sidebar',
                'par_class': 'sidebar',
                'text_src': f'dtbook.xml#sidebar_{marker.value}'
            }
        elif marker.type == 'annotation':
            return {
                'seq_class': 'annotation',
                'par_class': 'annotation',
                'text_src': f'dtbook.xml#annot_{marker.value}'
            }
        elif marker.type == 'prodnote':
            return {
                'seq_class': 'prodnote',
                'par_class': 'prodnote',
                'text_src': f'dtbook.xml#prodnote_{marker.value}'
            }
        return None


# 사용 예시:
if __name__ == '__main__':
    sample_text = """
    첫 번째 문단입니다.
    $#1
    두 번째 문단입니다.
    $note{이것은 각주입니다.}
    세 번째 문단입니다.
    $#2
    네 번째 문단입니다.
    $sidebar{이것은 사이드바 내용입니다.}
    """

    processed_text, markers = MarkerProcessor.process_text(sample_text)
    print("처리된 텍스트:", processed_text)
    print("\n발견된 마커들:")
    for marker in markers:
        print(f"- 타입: {marker.type}, 값: {marker.value}")
        dtbook_elem = MarkerProcessor.create_dtbook_element(marker)
        if dtbook_elem:
            print(f"  DTBook 요소: {dtbook_elem}")
