# Worker de Compilación de Apuntes (LaTeX)

Este repositorio público actúa como el motor de compilación (*worker*) remoto para el **Visor de Administración**.

### Funcionamiento
- Recibe solicitudes automáticas de compilación mediante GitHub Actions (`workflow_dispatch`).
- Compila o procesa los apuntes LaTeX / PDF de manera remota, gratuita e ilimitada.
- Guarda el resultado en la rama del grado correspondiente en el repositorio general (`apuntes/*.pdf`).
