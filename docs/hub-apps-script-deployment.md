# HUB Apps Script GitHub 관리 / 배포

목표: 법령정책 HUB Apps Script의 전체 소스를 GitHub에서 관리하고, `clasp` + GitHub Actions로 Apps Script에 반영한다.

## 구조

- `apps-script/hub/` : HUB Apps Script 전체 소스의 GitHub 원본
- `.github/workflows/hub-apps-script-sync.yml` : 현재 라이브 Apps Script 소스를 GitHub로 가져오는 수동 동기화
- `.github/workflows/hub-apps-script-deploy.yml` : `main`의 `apps-script/hub/**` 변경을 Apps Script와 기존 Web App에 자동 배포

`apps-script/AssemblyScheduler.gs`는 국회 수집기 스케줄러이므로 HUB 본체와 분리 유지한다.

## 최초 1회 필요한 GitHub Actions Secrets

Repository > Settings > Secrets and variables > Actions > New repository secret 에 아래 3개를 등록한다.

### 1. `HUB_APPS_SCRIPT_ID`

Apps Script 편집기 > 프로젝트 설정 > 스크립트 ID.

### 2. `HUB_CLASPRC_JSON`

`clasp login`으로 생성된 사용자 OAuth 인증 파일 전체 JSON.

Windows 기준 일반 경로:

```text
%USERPROFILE%\.clasprc.json
```

이 값은 인증 토큰이므로 코드나 채팅, 공개 저장소에 붙이지 않고 GitHub Secret에만 저장한다.

로컬 최초 로그인 예시:

```bash
npm install -g @google/clasp
clasp login
```

브라우저에서 HUB Apps Script를 소유/수정할 수 있는 Google 계정으로 승인한다.

### 3. `HUB_APPS_SCRIPT_DEPLOYMENT_ID`

Apps Script > 배포 > 배포 관리 > 현재 HUB Web App 배포 > 배포 ID.

이 값은 기존 Web App URL을 유지하면서 새 버전으로 배포할 때 사용한다.

## 최초 연결 순서

1. 위 Secret 3개 등록
2. GitHub Actions에서 **Sync HUB Apps Script source** 수동 실행
3. 워크플로가 라이브 프로젝트를 `clasp pull`하여 `apps-script/hub/`에 자동 커밋
4. `apps-script/hub/`에 `Code.gs`, `appsscript.json` 및 전체 `.gs` 파일이 들어왔는지 확인
5. 이 최초 Sync 커밋이 `main`에 반영되면 Deploy workflow가 자동 실행되어 동일 소스를 Apps Script/Web App에 다시 배포
6. 이후 HUB 수정은 GitHub `apps-script/hub/`만 수정하면 `main` 반영 시 자동 배포

## 수동 배포

필요하면 GitHub Actions의 **Deploy HUB Apps Script**를 직접 실행할 수도 있다.

- `deploy_webapp=false`: Apps Script 편집기 HEAD 소스만 갱신
- `deploy_webapp=true`: HEAD push 후 기존 Web App deployment ID도 새 버전으로 갱신

## 운영 원칙

- 최초 `Sync` 완료 전에는 Deploy를 실행하지 않는다.
- Deploy는 `appsscript.json`과 최소 5개 이상의 `.gs` 파일이 없으면 실패하도록 방어한다.
- 기존 Web App URL을 유지해야 하므로 새 deployment를 만들지 않고 기존 `HUB_APPS_SCRIPT_DEPLOYMENT_ID`를 갱신한다.
- Script Properties (`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `DAILY_REPORT_EMAILS`, Gemini API Key 등)는 소스 저장소에 넣지 않는다. 기존 Apps Script 프로젝트 속성을 그대로 사용한다.
- GitHub Secret 값, 특히 `HUB_CLASPRC_JSON`, 은 채팅/코드/공개 저장소에 노출하지 않는다.
- 코드 변경 전 필요하면 Sync workflow를 실행해 라이브 소스와 GitHub를 다시 맞출 수 있다.

## 이후 작업 방식

연결 완료 후에는 사용자가 Apps Script 코드를 채팅에 복사할 필요가 없다.

1. GitHub `apps-script/hub/`에서 현재 코드 확인
2. 필요한 코드 수정
3. `main`에 반영
4. GitHub Actions가 Apps Script + 기존 Web App에 자동 배포
5. 필요 시 Actions 로그로 배포 성공/실패 확인

이 구조로 HUB와 국회 수집기 양쪽을 같은 GitHub 저장소에서 추적할 수 있다.
