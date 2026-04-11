{{/*
Common labels
*/}}
{{- define "swarm-reasoning.labels" -}}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/instance: {{ .Release.Name }}
helm.sh/chart: {{ .Chart.Name }}-{{ .Chart.Version }}
{{- end }}

{{/*
Selector labels for a specific component
*/}}
{{- define "swarm-reasoning.selectorLabels" -}}
app.kubernetes.io/name: {{ .name }}
app.kubernetes.io/instance: {{ .instance }}
{{- end }}

{{/*
Full name helper
*/}}
{{- define "swarm-reasoning.fullname" -}}
{{ .Release.Name }}
{{- end }}
