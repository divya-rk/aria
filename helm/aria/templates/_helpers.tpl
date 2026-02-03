{{/*
Expand the name of the chart.
*/}}
{{- define "aria.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
*/}}
{{- define "aria.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- printf "%s-%s" $name .Values.global.environment | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}

{{/*
Create chart name and version as used by the chart label.
*/}}
{{- define "aria.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "aria.labels" -}}
helm.sh/chart: {{ include "aria.chart" . }}
{{ include "aria.selectorLabels" . }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
environment: {{ .Values.global.environment }}
{{- end }}

{{/*
Selector labels
*/}}
{{- define "aria.selectorLabels" -}}
app.kubernetes.io/name: {{ include "aria.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Create the name of the service account to use
*/}}
{{- define "aria.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "aria.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}

{{/*
ECR registry URL
*/}}
{{- define "aria.registry" -}}
{{- if .Values.image.registry }}
{{- .Values.image.registry }}
{{- else }}
{{- printf "%s.dkr.ecr.%s.amazonaws.com" .Values.global.awsAccountId .Values.global.region }}
{{- end }}
{{- end }}

{{/*
S3 bucket names with defaults
*/}}
{{- define "aria.rawBucket" -}}
{{- if .Values.s3.rawBucket }}
{{- .Values.s3.rawBucket }}
{{- else }}
{{- printf "%s-raw-%s" .Values.global.project .Values.global.environment }}
{{- end }}
{{- end }}

{{- define "aria.outputBucket" -}}
{{- if .Values.s3.outputBucket }}
{{- .Values.s3.outputBucket }}
{{- else }}
{{- printf "%s-output-%s" .Values.global.project .Values.global.environment }}
{{- end }}
{{- end }}

{{- define "aria.lancedbBucket" -}}
{{- if .Values.s3.lancedbBucket }}
{{- .Values.s3.lancedbBucket }}
{{- else }}
{{- printf "%s-lancedb-%s" .Values.global.project .Values.global.environment }}
{{- end }}
{{- end }}

{{/*
DynamoDB table name
*/}}
{{- define "aria.dynamodbTable" -}}
{{- if .Values.dynamodb.tableName }}
{{- .Values.dynamodb.tableName }}
{{- else }}
{{- printf "%s-pipeline-state-%s" .Values.global.project .Values.global.environment }}
{{- end }}
{{- end }}

{{/*
Generic S3 bucket name helper
Usage: {{ include "aria.s3Bucket" (dict "Values" .Values "bucket" "tokenized") }}
*/}}
{{- define "aria.s3Bucket" -}}
{{- printf "%s-%s-%s" .Values.global.project .bucket .Values.global.environment }}
{{- end }}
