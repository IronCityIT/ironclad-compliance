// Ironclad Compliance — quality gates and assessment runner.
//
// Two jobs in one pipeline, selected by the RUN_ASSESSMENT parameter:
//
//   default            the gate pipeline: format, lint, typecheck, test,
//                      artifact validation, build, security. Every gate runs
//                      even after one fails, so a single run reports every
//                      problem rather than one at a time; the build is marked
//                      FAILURE at the end if any gate failed.
//
//   RUN_ASSESSMENT     run a real assessment for a client against a framework
//                      and archive the report and the auditor package.
//
// Nothing here echoes a secret. Credentials are bound only inside the step that
// needs them, and the assessment stage passes the client id through the
// environment rather than interpolating it into a shell command.

pipeline {
  agent {
    docker {
      image 'python:3.11-slim'
      // The agent needs no privileged access; the engine core is stdlib-only.
      args '-u root:root'
    }
  }

  options {
    timestamps()
    ansiColor('xterm')
    timeout(time: 30, unit: 'MINUTES')
    buildDiscarder(logRotator(numToKeepStr: '30', artifactNumToKeepStr: '10'))
    disableConcurrentBuilds()
  }

  parameters {
    booleanParam(
      name: 'RUN_ASSESSMENT',
      defaultValue: false,
      description: 'Run a compliance assessment instead of the gate pipeline'
    )
    string(
      name: 'CLIENT_ID',
      defaultValue: '',
      description: 'Client identifier (assessment runs only)'
    )
    choice(
      name: 'FRAMEWORK',
      choices: ['soc2', 'nist-csf', 'pci-dss', 'hipaa'],
      description: 'Framework to assess against'
    )
    choice(
      name: 'GROUP',
      choices: ['deep', 'standard', 'quick'],
      description: 'Capability group to run'
    )
    string(
      name: 'EVIDENCE_DIR',
      defaultValue: 'evidence',
      description: 'Directory of collected evidence, relative to the workspace'
    )
  }

  environment {
    PIP_DISABLE_PIP_VERSION_CHECK = '1'
    PIP_NO_CACHE_DIR = '1'
    PYTHONDONTWRITEBYTECODE = '1'
    // Gate results accumulate here so the summary can name every failure.
    GATE_FAILURES = ''
  }

  stages {

    stage('Checkout') {
      steps {
        checkout scm
        sh 'git --no-pager log -1 --pretty="%h %an %s"'
      }
    }

    stage('Setup') {
      steps {
        sh '''
          set -eu
          python -m pip install --quiet --upgrade pip
          pip install --quiet -r requirements-dev.txt
          pip install --quiet build
          python --version
          ruff --version
          mypy --version
          pytest --version
        '''
      }
    }

    stage('Gates') {
      when { expression { !params.RUN_ASSESSMENT } }
      steps {
        script {
          // Each gate runs regardless of the ones before it. A pipeline that
          // stops at the first red gate makes a developer discover the next
          // failure only after fixing this one.
          def gates = [
            [name: 'format',   cmd: 'ruff format --check .'],
            [name: 'lint',     cmd: 'ruff check --output-format=concise .'],
            [name: 'typecheck', cmd: 'mypy'],
            [name: 'test',     cmd: 'pytest --cov=ironclad --cov-report=xml --cov-report=term-missing --junitxml=junit.xml'],
            [name: 'artifacts', cmd: 'python scripts/validate_artifacts.py'],
            [name: 'build',    cmd: 'python -m build'],
          ]

          def failed = []
          for (gate in gates) {
            echo "── gate: ${gate.name}"
            def status = sh(script: gate.cmd, returnStatus: true)
            if (status != 0) {
              failed << gate.name
              echo "── gate ${gate.name} FAILED (exit ${status})"
            } else {
              echo "── gate ${gate.name} passed"
            }
          }

          // The Cloud Functions gate needs a runtime this agent image does not
          // carry. Same contract as the security gate below: an agent that
          // cannot run it says so rather than reporting a pass it did not earn.
          def functionsStatus = sh(
            script: '''
              set -eu
              command -v npm >/dev/null 2>&1 || {
                echo "node/npm unavailable on this agent"; exit 66; }
              npm --prefix functions run lint
              npm --prefix functions test
            ''',
            returnStatus: true
          )
          if (functionsStatus == 66) {
            echo '── gate functions UNAVAILABLE — reported, not passed'
            unstable('cloud functions gate could not run on this agent')
          } else if (functionsStatus != 0) {
            failed << 'functions'
            echo '── gate functions FAILED'
          } else {
            echo '── gate functions passed'
          }

          // Security scanning is best-effort: the tools are not pinned into the
          // dev requirements, so an agent without them reports the gate as
          // unavailable rather than silently passing it.
          def securityStatus = sh(
            script: '''
              set -eu
              pip install --quiet pip-audit bandit 2>/dev/null || {
                echo "security tooling unavailable on this agent"; exit 66; }
              pip-audit --strict --desc || exit 1
              bandit -q -r ironclad scripts -x tests || exit 1
            ''',
            returnStatus: true
          )
          if (securityStatus == 66) {
            echo '── gate security UNAVAILABLE — reported, not passed'
            unstable('security gate could not run on this agent')
          } else if (securityStatus != 0) {
            failed << 'security'
            echo '── gate security FAILED'
          } else {
            echo '── gate security passed'
          }

          env.GATE_FAILURES = failed.join(', ')
          if (failed) {
            // A red gate blocks the change. It is reported in full above and
            // named in the build description; it is never papered over.
            error("quality gates failed: ${env.GATE_FAILURES}")
          }
        }
      }
      post {
        always {
          junit testResults: 'junit.xml', allowEmptyResults: true
          archiveArtifacts artifacts: 'junit.xml,coverage.xml,dist/*', allowEmptyArchive: true, fingerprint: true
        }
      }
    }

    stage('Smoke') {
      when { expression { !params.RUN_ASSESSMENT } }
      steps {
        sh '''
          set -eu
          python -m ironclad.cli list-modules > /dev/null
          python -m ironclad.cli list-frameworks > /dev/null
          for framework in soc2 nist-csf pci-dss hipaa; do
            python -m ironclad.cli validate --framework "$framework"
          done
          echo "smoke checks passed"
        '''
      }
    }

    stage('Assessment') {
      when { expression { params.RUN_ASSESSMENT } }
      steps {
        script {
          if (!params.CLIENT_ID?.trim()) {
            error('CLIENT_ID is required when RUN_ASSESSMENT is set')
          }
        }
        sh 'pip install --quiet PyPDF2 python-docx openpyxl'
        withEnv([
          "CLIENT_ID=${params.CLIENT_ID}",
          "FRAMEWORK=${params.FRAMEWORK}",
          "GROUP=${params.GROUP}",
          "EVIDENCE_DIR=${params.EVIDENCE_DIR}",
        ]) {
          sh '''
            set -eu
            if [ ! -d "$EVIDENCE_DIR" ]; then
              echo "evidence directory not found: $EVIDENCE_DIR" >&2
              exit 2
            fi
            python -m ironclad.cli assess \
              --client "$CLIENT_ID" \
              --framework "$FRAMEWORK" \
              --evidence-dir "$EVIDENCE_DIR" \
              --group "$GROUP" \
              --out out/
            python -m ironclad.cli export \
              --input out/assessment.json --format package --out out/package/
            python scripts/validate_artifacts.py out/assessment.json out/package/package.json
          '''
        }
      }
      post {
        always {
          // Archived for audit: the report, the machine record and the
          // hash-chained trail are the evidence that this assessment ran.
          archiveArtifacts(
            artifacts: 'out/assessment.json,out/report.html,out/package/**',
            allowEmptyArchive: true,
            fingerprint: true
          )
        }
      }
    }

    stage('Publish') {
      when {
        allOf {
          expression { params.RUN_ASSESSMENT }
          expression { currentBuild.currentResult == 'SUCCESS' }
        }
      }
      steps {
        // Bound only here, and only for the duration of this step.
        withCredentials([
          string(credentialsId: 'ironclad-store-results-url', variable: 'STORE_RESULTS_URL'),
          string(credentialsId: 'ironclad-ingest-api-key', variable: 'INGEST_API_KEY'),
        ]) {
          withEnv(["CLIENT_ID=${params.CLIENT_ID}"]) {
            sh '''
              set -eu
              python scripts/store_results.py \
                --client-id "$CLIENT_ID" \
                --results-dir out/ \
                --report-dir out/
            '''
          }
        }
      }
    }
  }

  post {
    success {
      script {
        currentBuild.description = params.RUN_ASSESSMENT
          ? "assessment: ${params.CLIENT_ID} / ${params.FRAMEWORK}"
          : 'all gates green'
      }
      echo "BUILD OK — ${currentBuild.description}"
    }
    unstable {
      echo 'BUILD UNSTABLE — a gate could not run. See the log above.'
    }
    failure {
      script {
        currentBuild.description = env.GATE_FAILURES
          ? "failed gates: ${env.GATE_FAILURES}"
          : 'build failed'
      }
      echo "BUILD FAILED — ${currentBuild.description}"
    }
    always {
      // Idempotent: a re-run starts from a clean workspace, so a stale report
      // from a previous build can never be archived as this build's output.
      cleanWs(
        deleteDirs: true,
        notFailBuild: true,
        patterns: [[pattern: 'out/**', type: 'INCLUDE'], [pattern: 'dist/**', type: 'INCLUDE']]
      )
    }
  }
}
