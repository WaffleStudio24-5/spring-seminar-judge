# spring-seminar-judge

스프링 세미나 과제를 채점하고, 과제별 통과 여부를 사이트에 표시합니다.

학생이 fork 저장소의 `main`에 push하면 공개된 과제를 각각 채점합니다. 사이트 상단의 **과제 v1~v5** 버튼으로 결과와 통계를 전환할 수 있습니다. 학생 저장소와 과제별로 마지막에 수신한 결과 한 행을 저장하며, 화면에는 선택한 과제의 최근 결과를 최대 100개 표시합니다. 이전 실행 전체를 보관하는 이력 시스템은 아닙니다.

## 구성과 채점 흐름

| 파일 | 역할 |
| --- | --- |
| [.github/workflows/grade.yml](.github/workflows/grade.yml) | 공개된 과제와 태그 목록 관리, 과제별 workflow 호출 |
| [.github/workflows/grade-assignment.yml](.github/workflows/grade-assignment.yml) | 과제 하나의 테스트 실행과 결과 전송 |
| [server.py](server.py) / [api/results.py](api/results.py) | GitHub OIDC 인증, 결과 저장·조회, Vercel 진입점 |
| [dashboard/index.html](dashboard/index.html) | 과제별 결과와 통계 화면 |
| [supabase/migrations](supabase/migrations) | 결과 테이블과 권한 변경 이력 |
| [grade.sh](grade.sh) | Docker를 이용한 로컬 채점 |

v1과 v2를 공개했을 때의 흐름입니다. 현재 채점 목록에는 v1이 등록돼 있습니다.

```text
학생 main push → grade.yml
                  ├─ grade-assignment.yml(v1, assignment-v1) → v1 결과
                  └─ grade-assignment.yml(v2, assignment-v2) → v2 결과
                                                               ↓
                                                    Vercel Result API
                                                               ↓
                                                    Supabase → 대시보드
```

각 채점은 upstream의 지정 태그를 checkout하고 학생의 `src/main`만 덮어쓴 뒤 `./gradlew test --no-daemon`을 실행합니다. 학생 저장소의 테스트 코드와 빌드 설정은 사용하지 않습니다. 한 과제가 실패해도 다른 과제는 계속 실행합니다.

`grade-assignment.yml` 안에서 테스트를 실행하는 `grade` job과 결과를 전송하는 `report` job은 별도 runner에서 실행합니다. OIDC 토큰 발급 권한은 `report` job에만 부여합니다.

## 처음 설정하기

### 1. Supabase 연결과 마이그레이션

Supabase 프로젝트를 만들고 이 GitHub 저장소를 연결합니다. 자동 마이그레이션 적용을 활성화하고, 운영 DB에 연결할 Git 브랜치를 확인합니다. Preview DB와 운영 DB는 별도 환경이므로 각각의 적용 상태를 확인해야 합니다.

**DB 변경은 마이그레이션 파일로 관리합니다.** GitHub 연동이 설정된 대상 브랜치에 변경을 반영하면 Supabase가 미적용 SQL을 실행하고 완료 이력을 자동으로 기록합니다. 파일을 만들거나 push하는 것만으로 모든 프로젝트에 자동 적용되는 것은 아니며, GitHub 연동과 배포 설정이 필요합니다.

SQL Editor에 마이그레이션 SQL을 직접 붙여 실행하면 적용 이력에 기록되지 않습니다. 새 설치에서는 이 방식을 사용하지 마세요. 기존에 수동 실행했다면 아래의 '마이그레이션 이력 복구'를 참고합니다. [Supabase 마이그레이션 문서](https://supabase.com/docs/guides/deployment/database-migrations)

CLI는 Node.js 20 이상에서 `npx`로 실행할 수 있습니다. 이 저장소에는 `supabase/config.toml`이 있으므로 `init`을 다시 실행할 필요가 없습니다.

```bash
npx supabase --version
npx supabase login
npx supabase link --project-ref <대상-프로젝트-ID>
npx supabase migration list
```

프로젝트 ID는 대시보드 URL의 `/project/<프로젝트-ID>` 부분입니다. 로그인 토큰과 DB 비밀번호는 CLI의 입력 요청에 따라 입력하고 Git에 저장하지 않습니다.

GitHub 자동 적용을 사용하지 않는 환경에서는 CLI로 적용합니다. 이 경우에도 완료 이력은 자동으로 기록됩니다.

```bash
npx supabase db push --dry-run
npx supabase db push
npx supabase migration list
```

원격 적용과 이력 조회에는 로컬 Supabase 실행이나 Docker가 필요하지 않습니다. [CLI 설치 안내](https://supabase.com/docs/guides/local-development/cli/getting-started)

### 2. Vercel 배포

Vercel에서 이 저장소를 import합니다. Framework Preset은 `Other`, Root Directory는 저장소 루트이며 별도 Build Command는 필요 없습니다.

Supabase 프로젝트의 URL과 Secret key를 확인하고 Vercel 환경변수를 설정합니다.

```dotenv
SUPABASE_URL=https://<project-ref>.supabase.co
SUPABASE_SECRET_KEY=sb_secret_...
OIDC_AUDIENCE=seminar-judge
ALLOWED_SOURCE_REPOSITORY=WaffleStudio24-5/spring-seminar-upstream
ALLOWED_WORKFLOW_REF=WaffleStudio24-5/spring-seminar-judge/.github/workflows/grade-assignment.yml@refs/heads/main
```

Secret key는 서버 환경에만 저장합니다. 학생 저장소나 프론트엔드에는 넣지 않습니다. Vercel Preview를 사용한다면 해당 환경의 DB URL과 키도 별도로 설정합니다.

`ALLOWED_SOURCE_REPOSITORY`는 학생들이 fork할 원본 저장소입니다. API가 GitHub에서 fork 관계를 확인하므로 학생 저장소를 개별 등록할 필요가 없습니다. GitHub API 요청 제한에 걸린다면 metadata 읽기 권한이 있는 토큰을 `GITHUB_API_TOKEN`으로 설정할 수 있습니다.

배포 후 사이트는 `https://<vercel-project>.vercel.app/`, API는 `https://<vercel-project>.vercel.app/api/results`입니다. 환경변수를 변경하면 재배포해야 합니다.

### 3. 학생 workflow 연결

학생 저장소의 `.github/workflows/grade.yml`에 다음 내용을 넣습니다. 운영진 workflow를 호출하려면 이 judge 저장소도 공개돼 있어야 합니다.

```yaml
name: Grade assignment

on:
  push:
    branches: [main]

jobs:
  grade:
    permissions:
      contents: read
      id-token: write
    uses: WaffleStudio24-5/spring-seminar-judge/.github/workflows/grade.yml@main
    with:
      result_url: https://<vercel-project>.vercel.app/api
```

`result_url`에는 마지막 `/results`를 제외한 주소를 넣습니다. 생략하면 GitHub Actions 결과만 남기고 사이트에는 전송하지 않습니다. 기본 인증 설정은 공개 fork 저장소의 `main` push와 GitHub-hosted runner만 허용합니다.

### 기존 workflow에서 전환하기

기존에는 `grade.yml` 하나가 upstream의 최신 `main`으로 채점하고 결과를 전송했습니다. 현재는 공개 과제를 실행하는 진입점과 실제 채점·전송 workflow를 분리했습니다.

| 설정 | 변경 전 | 변경 후 |
| --- | --- | --- |
| 학생 workflow의 `uses` 파일 | `grade.yml` | `grade.yml` 유지 |
| Vercel `ALLOWED_WORKFLOW_REF`의 파일 | `grade.yml` | `grade-assignment.yml` |

학생의 `uses`는 처음 호출할 파일이고, `ALLOWED_WORKFLOW_REF`는 서버가 결과 전송을 신뢰할 파일입니다. 서버는 이 값을 OIDC 토큰의 `job_workflow_ref`와 비교합니다. [GitHub OIDC 문서](https://docs.github.com/en/actions/how-tos/secure-your-work/security-harden-deployments/oidc-with-reusable-workflows)

학생 저장소의 호출 경로를 유지하려고 진입점 이름을 `grade.yml`로 남겼습니다. 두 파일 이름을 맞바꾸면 Vercel 설정 대신 학생들의 호출 경로를 바꿔야 합니다. 확장자도 경로의 일부이므로 `.yml`과 `.yaml`을 구분합니다.

기존 운영 환경에서는 위의 새 `ALLOWED_WORKFLOW_REF` 값으로 한 번 변경하고 재배포합니다. 이후 과제 추가나 테스트 수정 때는 이 환경변수를 바꾸지 않습니다. 학생 workflow의 `permissions`도 위 예시와 일치하는지 확인합니다.

기존 `main` 채점에 사용한 테스트는 운영진이 v1과 동일하다고 확인했습니다. `20260916000000_copy_legacy_results_to_v1.sql`은 기존 결과를 v1으로 옮겼고, 후속 파일 `20260916010000_merge_legacy_results_into_v1.sql`은 이미 v1 결과가 있는 저장소의 중복 `main` 행을 삭제한 뒤 남은 `main` 행의 과제 이름을 v1으로 바꿉니다. 기존 결과의 SHA, 상태, 채점 시각은 보존합니다. 사이트에는 v1~v5만 표시합니다.

## 과제 공개와 테스트 수정

사이트의 과제 이름 `assignment`는 `v1`~`v5`입니다. `assignment_ref`는 채점에 사용할 upstream 태그이고, 결과의 `assignment_sha`는 실제 사용한 커밋입니다.

| 작업 | 사이트 과제 이름 | upstream 태그 |
| --- | --- | --- |
| 첫 과제 공개 | `v1` | `assignment-v1` |
| 두 번째 과제 공개 | `v2` | `assignment-v2` |
| 두 번째 과제 테스트 수정 | `v2` | `assignment-v2.1` |

`assignment-v1`은 upstream 커밋 [845a972](https://github.com/WaffleStudio24-5/spring-seminar-upstream/commit/845a97290b8c3862a31e390a865440ecad45bebb)에 생성돼 있습니다. 기존 태그를 다시 만들거나 옮기지 않습니다.

### 새 과제 공개

upstream의 `main`에서 여러 커밋으로 개발해도 채점 기준은 바뀌지 않습니다. v2가 완성되면 upstream 저장소에서 검증한 커밋에 태그를 붙이고 push합니다.

```bash
git tag -a assignment-v2 <검증한-커밋-SHA> -m "assignment v2"
git push origin refs/tags/assignment-v2
```

그다음 judge 저장소의 `grade.yml`에서 기존 항목을 유지하고 v2를 추가합니다.

```yaml
matrix:
  include:
    - assignment: v1
      assignment_ref: assignment-v1
    - assignment: v2
      assignment_ref: assignment-v2
```

judge의 `main`에 변경을 반영하면 다음 학생 push부터 v1과 v2를 각각 채점합니다. v3~v5도 같은 방식입니다. 태그만 만들면 채점 목록에 자동 등록되지 않습니다. 태그를 먼저 공개해야 하며, 없는 태그를 지정하면 checkout이 실패해 새 결과를 기록할 수 없습니다.

### 공개한 테스트 수정

수정 커밋에 새 태그를 붙입니다. v3 개발이 시작됐다면 v2의 기존 태그에서 수정 브랜치를 만들어, v3 코드가 섞이지 않도록 합니다.

```bash
git tag -a assignment-v2.1 <검증한-커밋-SHA> -m "assignment v2 test fix 1"
git push origin refs/tags/assignment-v2.1
```

`grade.yml`에서 v2 항목의 태그만 바꿉니다.

```yaml
- assignment: v2
  assignment_ref: assignment-v2.1
```

사이트에서는 계속 v2로 묶입니다. 새 결과가 들어오면 해당 학생의 v2 결과만 교체되고 다른 과제 결과는 유지됩니다. 다시 수정하면 `assignment-v2.2`처럼 번호를 올립니다.

태그나 workflow를 바꿔도 기존 제출은 자동 재채점되지 않습니다. 새 기준으로 채점하려면 학생 저장소의 `main`에 새 push가 필요합니다. 코드 변경이 없다면 빈 커밋을 사용할 수 있습니다. 기존 실행 재시도는 과거 workflow를 사용할 수 있으므로 새 기준 적용에는 새 push를 사용합니다.

## 마이그레이션 운영과 오류 복구

새 DB 변경은 `npx supabase migration new <이름>`으로 파일을 만들고 SQL을 작성합니다. 적용한 파일은 유지하고 후속 변경을 새 파일로 추가합니다. GitHub 연동으로 배포한 뒤 `npx supabase migration list`의 `REMOTE` 열에서 적용 이력을 확인합니다.

### `relation "results" already exists`

테이블은 있지만 생성 마이그레이션의 실행 이력이 없으면 자동 배포가 같은 SQL을 다시 실행할 수 있습니다. SQL Editor에서 직접 적용했던 환경이라면 대상 DB에서 확인합니다.

```sql
select version
from supabase_migrations.schema_migrations
order by version;

select pg_get_constraintdef(oid)
from pg_constraint
where conrelid = 'public.results'::regclass
  and contype = 'p';
```

`PRIMARY KEY (repository, assignment)`는 두 번째 마이그레이션의 구조입니다. 기본 키만으로 모든 변경이 반영됐다고 단정할 수는 없으므로 컬럼, RLS, 권한까지 두 SQL 파일과 일치하는지 확인합니다.

**두 파일이 이미 온전히 반영됐고 실행 이력만 누락된 경우에만** 아래 명령으로 복구합니다. CLI가 실패한 환경과 같은 프로젝트에 연결돼 있어야 합니다.

```bash
npx supabase migration repair \
  20260902000000 20260904000000 \
  --status applied
npx supabase migration list
```

```text
 LOCAL          | REMOTE
----------------|----------------
 20260902000000 | 20260902000000
 20260904000000 | 20260904000000
```

`repair`는 테이블이나 데이터를 변경하지 않고 적용 이력만 수정합니다. 두 버전이 `REMOTE`에 표시되면 실패한 배포를 재실행합니다. 일부 SQL만 반영됐다면 나머지를 먼저 확인·적용해야 하며, 미적용 파일을 완료로 표시하면 안 됩니다. [복구 절차](https://supabase.com/docs/guides/deployment/database-migrations)

## API

### 결과 조회

`GET /api/results?assignment=v2`는 선택한 과제의 최근 결과 100개를 `{"results": [...]}`로 반환합니다. 필터를 생략하면 전체 과제 중 최근 100개를 반환합니다.

각 결과에는 `repository`, `assignment`, `assignment_sha`, `commit_sha`, `status`, `run_number`, `run_attempt`, `graded_at`이 포함됩니다. 대시보드의 통계도 이 조회 범위를 기준으로 계산합니다. v1~v5 버튼은 항상 표시되며 결과가 없으면 안내 메시지를 보여줍니다.

### 결과 제출

```http
POST /api/results
Content-Type: application/json
Authorization: Bearer <GitHub Actions OIDC token>

{
  "repository": "user/assignment",
  "commit": "0123456789abcdef0123456789abcdef01234567",
  "assignment": "v1",
  "assignment_sha": "0123456789abcdef0123456789abcdef01234567",
  "status": "PASSED",
  "run_id": "123",
  "run_number": "4",
  "run_attempt": "1"
}
```

`status`는 `PASSED`, `FAILED`, `ERROR` 중 하나이고, 신규 제출의 `assignment`는 v1~v5만 허용합니다. API는 OIDC 서명, 학생 저장소·커밋, 실행 정보, 허용 workflow와 fork 관계를 검증합니다. 과제 이름과 upstream SHA는 형식을 검사하고 신뢰하는 workflow가 전송한 값을 저장합니다.

## 로컬 실행과 검증

Python 3.12 이상에서 의존성을 설치하고, 위 Vercel 환경변수를 현재 셸에 설정한 뒤 실행합니다. 서버가 `.env` 파일을 자동으로 읽지는 않습니다.

```bash
python3 -m pip install -r requirements.txt
python3 server.py
```

사이트는 `http://127.0.0.1:8080/`, API는 `/api/results`입니다. `/results`도 같은 JSON API로 동작합니다. `HOST`, `PORT`로 수신 주소를 바꿀 수 있고, 학생의 허용 브랜치는 `ALLOWED_REF`로 설정합니다. 기본값은 `refs/heads/main`입니다.

서버 테스트는 실제 Supabase 연결 없이 실행합니다.

```bash
python3 -m unittest -v
```

Docker가 설치된 환경에서는 학생 저장소와 커밋을 지정해 로컬 채점도 할 수 있습니다.

```bash
UPSTREAM_REF=refs/tags/assignment-v1 ./grade.sh <학생-저장소> <학생-커밋-SHA>
```

기본 upstream 경로는 같은 상위 디렉터리의 `spring-seminar-upstream`이며, `UPSTREAM_REPOSITORY`로 변경할 수 있습니다. 로컬 upstream에 해당 태그가 있어야 합니다. `UPSTREAM_REF`를 생략하면 upstream의 `HEAD`로 채점합니다. 로컬 채점 결과는 터미널에 출력하며 사이트에는 전송하지 않습니다.
