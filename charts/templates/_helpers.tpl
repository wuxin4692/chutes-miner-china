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
