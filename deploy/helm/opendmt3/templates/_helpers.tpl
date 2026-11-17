{{/*
Names and labels. Every object is called by the release's full name ("opendmt3" for a release called opendmt3,
"dmt3-opendmt3" for one called dmt3).
*/}}

{{/* The chart's name, or nameOverride. */}}
{{- define "opendmt3.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/* The objects' name: fullnameOverride, else the release's name with the chart's unless it holds it already. */}}
{{- define "opendmt3.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- $name := default .Chart.Name .Values.nameOverride -}}
{{- if contains $name .Release.Name -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}
{{- end -}}

{{/* The labels the pod is selected by: never changed after install, which a Deployment refuses. */}}
{{- define "opendmt3.selectorLabels" -}}
app.kubernetes.io/name: {{ include "opendmt3.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{/* Every label of the chart's objects. */}}
{{- define "opendmt3.labels" -}}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{ include "opendmt3.selectorLabels" . }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}

{{/* "repository:tag", the tag defaulting to the chart's appVersion (the server the chart was released with). */}}
{{- define "opendmt3.image" -}}
{{- printf "%s:%s" .Values.image.repository (toString (.Values.image.tag | default .Chart.AppVersion)) -}}
{{- end -}}

{{/* The Secret holding the first account's password: the owner's own, or the chart's. */}}
{{- define "opendmt3.adminSecret" -}}
{{- .Values.admin.existingSecret | default (printf "%s-admin" (include "opendmt3.fullname" .)) -}}
{{- end -}}

{{/* The volume's claim: the owner's own, or the chart's. */}}
{{- define "opendmt3.claim" -}}
{{- .Values.persistence.existingClaim | default (printf "%s-data" (include "opendmt3.fullname" .)) -}}
{{- end -}}

{{/*
The game's port as the cabinets reach it, which the server also listens on, so the site tells launchers the right one:
the node's port with type NodePort when one is named, else the Service's port.
*/}}
{{- define "opendmt3.gamePort" -}}
{{- if and (eq .Values.game.service.type "NodePort") .Values.game.service.nodePort -}}
{{ .Values.game.service.nodePort }}
{{- else -}}
{{ .Values.game.service.port }}
{{- end -}}
{{- end }}
