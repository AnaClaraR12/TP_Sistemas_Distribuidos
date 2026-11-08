/** Validações no cliente espelhando as do servidor. */

export const MAX_UPLOAD_MB = 50;

export function validarPdf(arquivo, maxMb = MAX_UPLOAD_MB) {
  if (!arquivo) return "Selecione um arquivo PDF.";
  const nome = (arquivo.name || "").toLowerCase();
  if (!nome.endsWith(".pdf")) return "Somente arquivos PDF são aceitos.";
  if (arquivo.type && !["application/pdf", "application/x-pdf"].includes(arquivo.type)) {
    return "Somente arquivos PDF são aceitos.";
  }
  if (arquivo.size > maxMb * 1024 * 1024) return `O arquivo excede ${maxMb} MB.`;
  if (arquivo.size === 0) return "Arquivo vazio.";
  return null;
}

export function validarAvaliacao({ nota, parecer, recomendacao }) {
  const erros = {};
  const n = Number(String(nota).replace(",", "."));
  if (nota === "" || nota === null || Number.isNaN(n)) erros.nota = "Informe a nota.";
  else if (n < 0 || n > 10) erros.nota = "A nota deve estar entre 0 e 10.";
  else if (!/^\d{1,2}([.,]\d)?$/.test(String(nota))) erros.nota = "Use no máximo uma casa decimal.";
  if (!parecer || parecer.trim().length < 50) erros.parecer = "O parecer deve ter pelo menos 50 caracteres.";
  if (!["aprovado_sem_ressalvas", "aprovado_com_ressalvas", "reprovado"].includes(recomendacao)) {
    erros.recomendacao = "Escolha uma recomendação.";
  }
  return erros;
}

export const ROTULOS_STATUS = {
  rascunho: "Rascunho",
  em_avaliacao: "Em avaliação",
  aprovada: "Aprovada",
  reprovada: "Reprovada",
  publicada: "Publicada",
  em_organizacao: "Em organização",
  agendada: "Agendada",
  realizada: "Realizada",
  cancelada: "Cancelada",
  pendente: "Pendente",
  confirmado: "Confirmado",
  recusado: "Recusado",
  rejeitada: "Rejeitada",
};

export const RECOMENDACOES = {
  aprovado_sem_ressalvas: "Aprovado sem ressalvas",
  aprovado_com_ressalvas: "Aprovado com ressalvas",
  reprovado: "Reprovado",
};

export function formatarData(iso, comHora = true) {
  if (!iso) return "—";
  const d = new Date(iso);
  return comHora ? d.toLocaleString("pt-BR") : d.toLocaleDateString("pt-BR");
}

export function formatarBytes(n) {
  if (!n && n !== 0) return "—";
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}
