# spring-seminar-judge
스프링 세미나 채점 workflow와 결과 수집 서버

## GitHub Actions 채점

공개 저장소의 reusable workflow를 학생 과제 저장소에서 호출합니다.

```yaml
jobs:
  grade:
    uses: WaffleStudio24-5/spring-seminar-judge/.github/workflows/grade.yml@main
    with:
      assignment: main
      assignment_sha: af730b224a94ec2540d2e51f95cbd3d0b92e3b6f
      result_url: https://<vercel-project>.vercel.app/api
```

workflow는 학생 저장소와 지정한 `spring-seminar-upstream` 버전을 각각 checkout한 뒤, 학생의 `src/main`만 원본 프로젝트에 적용해 테스트합니다.

공개 학생 저장소에서 호출하려면 이 저장소도 공개되어 있어야 합니다.

## 로컬 채점

학생 저장소의 특정 커밋을 upstream의 원본 빌드 설정과 테스트로 실행합니다.

```bash
./grade.sh <학생 저장소> <학생 커밋 SHA>
```

기본 upstream은 같은 상위 디렉터리의 `spring-seminar-upstream`이며, 다음 환경변수로 바꿀 수 있습니다.

```bash
UPSTREAM_REPOSITORY=/path/to/upstream UPSTREAM_REF=<commit> ./grade.sh <repo> <commit>
```

`result_url`을 생략하면 GitHub Actions 결과만 남기고 Result API에는 전송하지 않습니다.

## Result API 배포

### 1. Supabase

Supabase 프로젝트를 만든 뒤 SQL Editor에서
[`supabase/migrations/20260902000000_create_results.sql`](supabase/migrations/20260902000000_create_results.sql)을 실행합니다.
이 테이블은 같은 workflow run/attempt가 재전송돼도 한 행만 저장하고, RLS와 권한 회수로 공개 API 키 접근을 막습니다.

Dashboard의 **Project Settings → API Keys**에서 다음 값을 준비합니다.

- Project URL → `SUPABASE_URL`
- Secret key (`sb_secret_...`) → `SUPABASE_SECRET_KEY`

Secret key는 Vercel에만 저장하며 GitHub Actions나 학생 저장소에는 넣지 않습니다.

### 2. Vercel

Vercel에서 이 GitHub 저장소를 import합니다. Framework Preset은 `Other`, Root Directory는 저장소 루트로 둡니다.
별도 Build Command는 필요 없습니다. `api/results.py`가 `/api/results` Python Function으로 배포됩니다.

Production 환경변수를 설정합니다.

```dotenv
SUPABASE_URL=https://<project-ref>.supabase.co
SUPABASE_SECRET_KEY=sb_secret_...
OIDC_AUDIENCE=seminar-judge
ALLOWED_SOURCE_REPOSITORY=WaffleStudio24-5/spring-seminar-upstream
ALLOWED_ASSIGNMENTS=main=af730b224a94ec2540d2e51f95cbd3d0b92e3b6f
ALLOWED_WORKFLOW_REF=WaffleStudio24-5/spring-seminar-judge/.github/workflows/grade.yml@refs/heads/main
ALLOWED_WORKFLOW_SHAS=<배포한 judge commit SHA>
```

`ALLOWED_SOURCE_REPOSITORY`에는 학생들이 fork할 원본 저장소를 넣습니다. 제출 시 GitHub API에서 실제 fork 관계를 자동 검증하므로 학생 저장소를 하나씩 등록할 필요가 없습니다. 공개 API 제한에 걸릴 정도로 제출이 많다면 metadata 읽기 권한만 가진 fine-grained token을 `GITHUB_API_TOKEN`으로 추가할 수 있습니다. 여러 workflow SHA는 쉼표로 구분하며, `ALLOWED_WORKFLOW_SHAS`에는 reusable workflow 파일을 포함한 judge 커밋 SHA를 넣습니다.

배포 후 API 주소가 다음과 같이 생깁니다.

```text
https://<vercel-project>.vercel.app/api/results
```

학생용 workflow의 `result_url`에는 끝의 `/results`를 제외한 base URL을 넣습니다.

```yaml
result_url: https://<vercel-project>.vercel.app/api
```

### 3. 요청 형식

```bash
python3 -m pip install -r requirements.txt
SUPABASE_URL=https://<project-ref>.supabase.co \
SUPABASE_SECRET_KEY=sb_secret_... \
OIDC_AUDIENCE=seminar-judge \
ALLOWED_SOURCE_REPOSITORY=WaffleStudio24-5/spring-seminar-upstream \
ALLOWED_ASSIGNMENTS=assignment-1-v1=0123456789abcdef0123456789abcdef01234567 \
ALLOWED_WORKFLOW_REF=WaffleStudio24-5/spring-seminar-judge/.github/workflows/grade.yml@refs/heads/main \
ALLOWED_WORKFLOW_SHAS=<허용할 judge workflow commit SHA> \
python3 server.py
```

```http
POST /results
Content-Type: application/json
Authorization: Bearer <GitHub Actions OIDC token>

{
  "repository": "user/assignment",
  "commit": "0123456789abcdef0123456789abcdef01234567",
  "assignment": "assignment-1-v1",
  "assignment_sha": "0123456789abcdef0123456789abcdef01234567",
  "status": "PASSED",
  "run_id": "123",
  "run_number": "4",
  "run_attempt": "1"
}
```

API는 GitHub 서명과 함께 repository, commit, run ID, `job_workflow_ref`, `job_workflow_sha`를 검증합니다. 허용 목록은 쉼표로 구분하며 기본적으로 `main` push만 허용합니다. 브랜치는 `ALLOWED_REF`로 변경할 수 있습니다.

`GET /api/results`는 최근 결과 100개를 공개 JSON으로 반환합니다.

## 결과 대시보드 배포

같은 저장소를 Vercel에 프로젝트 하나 더 import하고 Root Directory를 `dashboard`로 설정합니다. Framework Preset은 `Other`로 두고 Build Command는 비워 둡니다. `dashboard/index.html`이 Result API를 읽어 최신 결과를 표시합니다.

로컬에서는 같은 환경변수를 지정하고 `python3 server.py`를 실행하면 `http://127.0.0.1:8080/results`에서 확인할 수 있습니다.

## 전체 채점 흐름

1. 학생이 fork의 `main`에 push합니다.
2. 학생 workflow가 운영진 reusable workflow를 호출합니다.
3. GitHub-hosted Runner가 고정된 upstream commit을 checkout하고 학생 `src/main`만 덮어쓴 뒤 원본 테스트를 실행합니다.
4. report job이 결과와 GitHub OIDC token을 Vercel `/api/results`로 전송합니다.
5. Vercel은 OIDC 서명, 학생 저장소/커밋, 원본 과제 커밋, reusable workflow 경로/커밋을 검증합니다.
6. 검증을 통과한 결과만 Supabase `results` 테이블에 저장됩니다.
