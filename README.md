# UPBIT 전략 V22 Mobile

V17·V20·V21의 장점을 독립 모듈로 보존하고, V22 누락방지 검증을 적용한 Streamlit 모바일 웹앱입니다.

## 핵심 기능

- V17 Legacy: 거래대금 상위30, 전일 성공추적, 단기 목표도달, 유동성, RSI, 전일캔들
- V20 Core: 거래대금 상위50, 20·10·5일 도달, 3일 상승, 순위급상승, 시장강도
- V21 Quality: 과열감점, 윗꼬리, RSI, 리스크, 추천 진입가격
- V22 Preservation: 기존 후보 자동 누락 금지, 모듈별 투표, 회귀검증
- 08:30 이후 실행 시 30분 캔들로 전일 09:00~당일 08:30 스냅샷 재구성
- 모바일 후보 카드, 모듈 비교, 백테스트, 누락방지 검증
- V22 Excel 및 CSV 다운로드

공개 시세 API만 사용하므로 업비트 API 키는 필요하지 않습니다.

## PC 실행

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Streamlit Community Cloud 배포

1. ZIP 압축을 풉니다.
2. 파일 전체를 GitHub 저장소에 올립니다.
3. Streamlit Community Cloud에서 Create app을 선택합니다.
4. Main file path를 `app.py`로 지정합니다.
5. Deploy 후 생성된 주소를 휴대폰에서 엽니다.
6. 브라우저 메뉴의 `홈 화면에 추가`를 사용하면 앱처럼 실행할 수 있습니다.

## Colab 임시 실행

함께 제공되는 `upbit_v22_mobile_colab_launcher.ipynb`를 Colab에서 열고,
`upbit_v22_mobile_app.zip`을 업로드합니다.

Colab 세션이 끝나면 임시 주소도 종료됩니다. 상시 사용은 Streamlit Community Cloud 배포가 적합합니다.

## 보존전략 잠금

모바일 설정에서 다음 항목은 변경할 수 없습니다.

- V17 거래대금 상위30
- V20 거래대금 상위50
- V17 유동성 기준
- V17/V20 등급 기준
- 기존 후보 최소 보존 규칙

목표수익률, 백테스트 일수, 지정가 하락폭, ETH 제외 여부만 변경할 수 있습니다.

## 주의

- 현재 후보는 08:30 스냅샷을 재구성합니다.
- 과거 백테스트는 완료 일봉 기반 08:30 프록시입니다.
- 지정가 목표도달률은 일봉 내 고가와 저가의 발생 순서를 확인할 수 없어 참고용입니다.
