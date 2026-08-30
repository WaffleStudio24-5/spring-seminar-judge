# spring-seminar-judge
스프링 세미나 채점 서버

## 로컬 채점

학생 저장소의 특정 커밋을 upstream의 원본 빌드 설정과 테스트로 실행합니다.

```bash
./grade.sh <학생 저장소> <학생 커밋 SHA>
```

기본 upstream은 같은 상위 디렉터리의 `spring-seminar-upstream`이며, 다음 환경변수로 바꿀 수 있습니다.

```bash
UPSTREAM_REPOSITORY=/path/to/upstream UPSTREAM_REF=<commit> ./grade.sh <repo> <commit>
```

## HTTP API

```bash
python3 -m pip install -r requirements.txt
OIDC_AUDIENCE=seminar-judge \
ALLOWED_REPOSITORY_OWNER=WaffleStudio24-5 \
ALLOWED_ASSIGNMENTS=assignment-1-v1 \
python3 server.py
```

```http
POST /gradings
Content-Type: application/json
Authorization: Bearer <GitHub Actions OIDC token>

{
  "repository": "https://github.com/user/assignment.git",
  "commit": "0123456789abcdef0123456789abcdef01234567",
  "assignment": "assignment-1-v1"
}
```

기본 주소는 `127.0.0.1:8080`입니다. 배포 환경에서는 `HOST`, `PORT`, `UPSTREAM_REPOSITORY`를 지정합니다.
기본적으로 `main` 브랜치의 토큰만 허용하며 `ALLOWED_REF`로 변경할 수 있습니다.
여러 과제 버전은 `ALLOWED_ASSIGNMENTS=assignment-1-v1,assignment-2-v1`처럼 쉼표로 구분합니다.
