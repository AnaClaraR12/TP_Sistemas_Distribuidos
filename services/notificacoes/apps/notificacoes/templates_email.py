from django.template import Context, Template

TEMPLATES: dict[str, tuple[str, str]] = {
    "submissao_orientador": (
        "Nova submissão aguardando sua aprovação",
        'Olá, {{ nome }}.\n\nA monografia "{{ titulo }}" foi submetida e aguarda sua aprovação.\n'
        "Acesse: {{ frontend }}/monografias/{{ monografia_id }}\n",
    ),
    "texto_extraido": (
        "Arquivo processado — pronto para avaliação",
        'Olá, {{ nome }}.\n\nO PDF da monografia "{{ titulo }}" foi processado ({{ paginas }} página(s))'
        "{% if sem_texto %}, mas não possui texto pesquisável (PDF escaneado){% endif %}.\n"
        "Acesse: {{ frontend }}/monografias/{{ monografia_id }}\n",
    ),
    "extracao_falhou": (
        "Falha ao processar o arquivo da monografia",
        'Olá, {{ nome }}.\n\nNão foi possível processar o PDF de "{{ titulo }}": {{ motivo }}.\n'
        "Verifique o arquivo e, se necessário, envie uma nova versão.\n",
    ),
    "aprovada_orientador": (
        "Aprovada pelo orientador; já pode ir à banca",
        'Olá, {{ nome }}.\n\nA monografia "{{ titulo }}" foi aprovada pelo orientador e já pode ter a banca agendada.\n',
    ),
    "rejeitada_orientador": (
        "Submissão devolvida pelo orientador",
        'Olá, {{ nome }}.\n\nSua submissão "{{ titulo }}" foi devolvida para ajustes.\nMotivo: {{ motivo }}\n',
    ),
    "convite_banca": (
        "Convite para banca de defesa de TCC",
        'Olá, {{ nome }}.\n\nVocê foi convidado(a) para a banca da monografia "{{ titulo }}".\n'
        "Data/hora: {{ data_hora }}\n{% if local %}Local: {{ local }}{% else %}Link: {{ link }}{% endif %}\n\n"
        "Confirme sua disponibilidade em: {{ url_convite }}\n"
        "{% if expira_em %}O acesso expira em {{ expira_em }}.{% endif %}\n",
    ),
    "banca_agendada": (
        "Banca de defesa agendada",
        'Olá, {{ nome }}.\n\nA banca da monografia "{{ titulo }}" está AGENDADA.\n'
        "Data/hora: {{ data_hora }} ({{ duracao }} min)\n"
        "{% if local %}Local: {{ local }}{% else %}Link: {{ link }}{% endif %}\n\nMembros:\n"
        "{% for m in membros %}- {{ m.nome }} ({{ m.funcao }})\n{% endfor %}",
    ),
    "banca_cancelada": (
        "Banca de defesa cancelada",
        'Olá, {{ nome }}.\n\nA banca da monografia "{{ titulo }}" foi cancelada.\nMotivo: {{ motivo }}\n',
    ),
    "resultado_banca": (
        "Resultado da banca de defesa",
        'Olá, {{ nome }}.\n\nResultado da banca de "{{ titulo }}": {{ resultado|upper }} (média {{ media }}).\n'
        "{% if resultado == 'aprovada' %}Próximos passos: {% if exige_correcao %}envie a versão corrigida para "
        "validação do orientador e {% endif %}envie o termo de autorização de publicação assinado.{% endif %}\n",
    ),
    "publicada": (
        "Seu TCC está publicado",
        'Olá, {{ nome }}.\n\nA monografia "{{ titulo }}" foi publicada no repositório público.\n'
        "Link público: {{ frontend }}/repositorio/{{ monografia_id }}\n",
    ),
    "integridade_violada": (
        "ALERTA CRÍTICO: integridade de arquivo violada",
        'Atenção, {{ nome }}.\n\nO arquivo da monografia "{{ titulo }}" ({{ monografia_id }}) foi alterado após a '
        "aprovação.\nHash esperado: {{ sha_esperado }}\nHash atual: {{ sha_atual }}\n",
    ),
}


def renderizar(tipo: str, contexto: dict) -> tuple[str, str]:
    assunto, corpo = TEMPLATES[tipo]
    return assunto, Template(corpo).render(Context(contexto, autoescape=False))
