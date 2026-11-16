// Configuración del servicio del bot en Railway (Infrastructure as Code; reemplaza a railway.json).
//
//   railway config plan    → muestra qué cambiaría en Railway, sin aplicar nada
//   railway config apply   → aplica los cambios
//
// Requiere el SDK (npm install) y la CLI de Railway. Solo administra el servicio del bot y su volumen:
// las variables (secretos) y el servicio Redis quedan fuera (`variables: { managed: false }`).
// En Git Bash para Windows, ejecutar la CLI con la ruta a railway.exe (ver README, sección Railway).
import { defineRailway, github, project, service, volume } from "railway/iac";

// Este repositorio administra solo sus propios recursos dentro del proyecto.
// https://docs.railway.com/infrastructure-as-code#multi-repo-projects
export const partial = "whatsappbot-kudo";

export default defineRailway(() => {
  // Volumen con la base SQLite (/data/kudo.db). NO quitar de aquí: sin esta declaración,
  // `railway config apply` lo desconectaría del servicio.
  const datos = volume("whatsappbot-kudo-volume", { region: "us-east4-eqdc4a", sizeMB: 5000 });

  const whatsappbotKudo = service("whatsappbot-kudo", {
    source: github("billcifra/whatsappbot-kudo", { branch: "master", checkSuites: false }),
    build: { builder: "DOCKERFILE", dockerfilePath: "Dockerfile" },
    deploy: {
      healthcheckPath: "/salud",
      healthcheckTimeout: 300,
      restartPolicyType: "ON_FAILURE",
      restartPolicyMaxRetries: 5,
    },
    // Una sola réplica a propósito: SQLite y el orden de mensajes por cliente viven en un único proceso.
    replicas: { "us-east4-eqdc4a": 1 },
    volumeMounts: { "/data": datos },   // clave = ruta de montaje; valor = el volumen
  });

  return project("trustworthy-growth", {
    variables: { managed: false },
    resources: [datos, whatsappbotKudo],
  });
});
