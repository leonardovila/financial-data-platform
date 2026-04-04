# Biblia AWS + Docker — financial-data-etl

Glosario de todo lo que el primate necesita saber para defender este proyecto.

---

## Docker (Local)

**Dockerfile**: Receta paso a paso para cocinar una imagen. Se lee de arriba a abajo, cada instrucción crea una layer.

**Imagen**: Snapshot congelado del resultado de ejecutar el Dockerfile. Es inmutable — una vez cocinada, no cambia. Es el .zip que contiene tu app lista para correr.

**Container**: Una instancia viva corriendo desde una imagen. Puede haber muchos containers de la misma imagen. Cuando muere, todo lo que tenía adentro se pierde (a menos que uses volumes).

**Layer**: Cada instrucción del Dockerfile (FROM, COPY, RUN, etc.) genera una layer. Docker cachea layers por hash — si nada cambió en una layer ni en las anteriores, la reutiliza. Por eso el orden del Dockerfile importa: ponés lo que cambia poco arriba (dependencias) y lo que cambia mucho abajo (tu código).

**Volume**: Disco externo que sobrevive a la muerte del container. Lo usás para datos que necesitan persistir (como los archivos de PostgreSQL local). `down` mata containers pero preserva volumes. `down -v` mata todo.

**docker compose build**: Cocina las imágenes desde los Dockerfiles. Si los archivos no cambiaron, usa cache. `--no-cache` fuerza rebuild total.

**docker compose up**: Levanta containers desde imágenes ya cocinadas. NO rebuildeá. Si cambiaste código, la imagen vieja sigue corriendo.

**docker compose up --build**: Build + up en un solo comando. Tu go-to diario.

**docker compose down**: Mata containers, preserva volumes y datos.

**docker compose down -v**: Nuclear. Mata containers Y borra volumes. Reset de fábrica.

**Multi-stage build**: Dockerfile con dos etapas. La primera (builder) instala compiladores y dependencias pesadas. La segunda (runtime) copia solo lo necesario para correr. Resultado: imagen final liviana, sin basura de compilación.

**Entrypoint**: El comando que corre cuando un container arranca. Se puede sobreescribir con `--entrypoint` para debugging.

---

## AWS — Conceptos generales

**Región (Region)**: Datacenter físico donde viven tus recursos. Vos elegiste `us-east-2` (Ohio). Todo lo que crees tiene que estar en la misma región para que se vean entre sí.

**VPC (Virtual Private Cloud)**: Tu red privada dentro de AWS. Es como un edificio de oficinas aislado de internet. Nada entra ni sale a menos que vos lo permitas. Todos tus servicios (RDS, Fargate, etc.) viven adentro.

**Subnet**: Pisos dentro del edificio (VPC). Hay subnets públicas (con acceso a internet) y privadas (aisladas). La DB va en subnet privada. La API necesita una puerta pública para recibir requests.

**Security Group**: Las reglas de las puertas. "Puerto 5432 solo acepta conexiones desde los containers de Fargate". "Puerto 443 acepta conexiones de cualquiera" (para la API). Es un firewall por servicio.

**DNS (Domain Name System)**: Una guía telefónica. Traduce nombres legibles (`financial-data.xxxxx.rds.amazonaws.com`) a direcciones IP. Tu RDS tiene un endpoint DNS fijo — esa es su dirección permanente.

---

## AWS — IAM (Identity and Access Management)

**IAM**: El sistema de permisos de AWS. Controla quién puede hacer qué.

**Usuario IAM**: Una identidad (como `leonardo-admin`) con credenciales propias. No es tu cuenta root de AWS — es un usuario dentro de la cuenta.

**Access Key + Secret Key**: Tu "usuario y contraseña" para usar AWS desde la terminal (CLI). La Access Key es el usuario (pública), la Secret Key es la contraseña (SECRETA, nunca se comparte, nunca se commitea).

**Política (Policy)**: Un documento que dice "este usuario puede hacer X, Y, Z". Por ejemplo: "puede pushear imágenes a ECR" o "puede crear Fargate tasks".

**MFA**: Autenticación de dos factores. Obligatorio en la cuenta root.

---

## AWS — Servicios que usamos

**RDS (Relational Database Service)**: Servicio administrado para bases de datos. Vos elegís el motor (PostgreSQL), el hardware (db.t4g.micro), y el disco (20 GiB EBS). AWS se encarga de backups, parches, reinicios. Es la bóveda fija donde viven los datos. Siempre encendido, siempre en la misma dirección.

- **db.t4g.micro**: Clase burstable. 2 vCPU, 1 GiB RAM. Acumula créditos cuando está idle, los gasta en picos (como cuando el ETL inserta miles de filas). Más que suficiente para tu volumen.
- **EBS (Elastic Block Store)**: El SSD de tu RDS. 20 GiB. Es un disco de red, no local — si AWS mueve tu instancia, el disco la sigue.

**ECR (Elastic Container Registry)**: El estante donde guardás tus imágenes Docker cocinadas. Es como Docker Hub pero privado y dentro de tu cuenta de AWS. Fargate baja las imágenes de acá.

**ECS (Elastic Container Service)**: El servicio que orquesta containers. No corre nada por sí mismo — necesita una plataforma de ejecución (Fargate o EC2).

**Fargate**: La plataforma serverless para correr containers. No administrás servidores, no ves instancias, no hacés SSH a nada. Le decís "corré esta imagen con 512MB de RAM" y Fargate busca dónde ponerla. Pagás solo por lo que usás (CPU/RAM por segundo).

- **Fargate Service**: Un container que corre 24/7 y se auto-reemplaza si muere. Para tu API.
- **Fargate Task**: Un container que corre una vez y muere. Para tu ETL (se dispara por cronjob).

**S3 (Simple Storage Service)**: Almacenamiento de archivos. Es un bucket donde tirás archivos y quedan accesibles por URL. Para tu frontend (los archivos compilados de React).

**CloudFront**: CDN (Content Delivery Network). Agarra los archivos de S3 y los distribuye en servidores por todo el mundo. Un usuario en Argentina descarga tu frontend desde un servidor cercano, no desde Ohio.

---

## Arquitectura final — Cómo encaja todo

```
[Usuario en Buenos Aires]
        |
        | (1) Abre tu URL
        v
   [CloudFront + S3]  ← archivos estáticos (React)
        |
        | (2) JS en el browser pide datos
        v
   [Load Balancer]  ← puerta pública, única entrada a la VPC
        |
        v
   ============ VPC (tu edificio privado) ============
   |                                                  |
   |  [Fargate Service: API]  ←→  [RDS: PostgreSQL]  |
   |                                                  |
   |  [Fargate Task: ETL]    ←→  [RDS: PostgreSQL]   |
   |  (corre 1x/día por cron)                        |
   ===================================================
```

**Flujo del usuario**: CloudFront → browser ejecuta React → API (en Fargate) → PostgreSQL (en RDS) → respuesta al browser.

**Flujo del ETL**: Cron dispara Fargate Task → ETL scrapeá TradingView → inserta en PostgreSQL (en RDS) → container muere.

**El frontend está AFUERA de la VPC.** Son archivos estáticos, no necesitan servidor. No tiene acceso a la DB ni sabe que existe.

---

## Comandos AWS CLI que usaste

```bash
# Ver quién sos (verificar credenciales)
aws sts get-caller-identity

# Login al registry de ECR (necesario antes de push)
aws ecr get-login-password --region us-east-2 | docker login --username AWS --password-stdin <account_id>.dkr.ecr.us-east-2.amazonaws.com

# Crear repositorio en ECR
aws ecr create-repository --repository-name financial-data-etl --region us-east-2

# Buildear, tagear y pushear imagen
docker build -t financial-data-etl .
docker tag financial-data-etl:latest <account_id>.dkr.ecr.us-east-2.amazonaws.com/financial-data-etl:latest
docker push <account_id>.dkr.ecr.us-east-2.amazonaws.com/financial-data-etl:latest
```

---

*Última actualización: 2026-04-04*
*Estado: RDS PostgreSQL creado. Siguiente paso: ECR (subir imágenes) → Fargate (correr containers en la nube).*
