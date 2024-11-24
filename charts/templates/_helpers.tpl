{{- define "postgres.labels" -}}
app.kubernetes.io/name: chutes-postgres
{{- end }}

{{- define "redis.labels" -}}
app.kubernetes.io/name: chutes-redis
{{- end }}

{{- define "registry.labels" -}}
app.kubernetes.io/name: chutes-registry
{{- end }}

{{- define "squid.labels" -}}
app.kubernetes.io/name: chutes-squid
{{- end }}

{{- define "chutes.labels" -}}
chute-deployment: "true"
{{- end }}

{{- define "bootstrap.labels" -}}
node-bootstrap: "true"
{{- end }}

{{- define "porter.labels" -}}
app.kubernetes.io/name: chutes-porter
{{- end }}

{{- define "minerApi.labels" -}}
app.kubernetes.io/name: chutes-miner-api
{{- end }}
