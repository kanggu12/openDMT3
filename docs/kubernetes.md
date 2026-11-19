# On Kubernetes

For server owners with a Kubernetes cluster. The Helm chart runs the same server as Docker: the released image, with
the game's port and the site in one pod and the data on one volume. The other ways to run a server are in
[Running a server](server.md).

## What it makes

- **One pod.** The database is SQLite on one volume, so there is one server, never two. An update stops the old pod
  before the new one starts.
- **A volume for the data.** The database, its daily backups, the song list and the installer to hand out. It stays
  when the chart is uninstalled, so installing again finds every account and play.
- **The game's Service.** TCP 4725, a `LoadBalancer` by default, so cabinets outside the cluster reach it. With
  `externalTrafficPolicy: Local` the server sees each cabinet's own address, which it tells cabinets apart by.
- **The site's Service.** Port 4730 inside the cluster, for an Ingress or `kubectl port-forward`.
- **The admin pages' Service.** Port 4731, always inside the cluster only (ClusterIP), for `kubectl port-forward`
  ([The admin pages](#the-admin-pages)).
- **An Ingress**, when asked for: the site at a host name, over HTTPS.

The pod runs as the image's own user (4725), with a read-only root file system, and answers `/health` for its probes.

## Install

Each release has the chart as `opendmt3-server-0.4.0-helm-chart.tgz`:

```sh
helm install dmt3 https://github.com/kanggu12/openDMT3/releases/download/v0.4.0/opendmt3-server-0.4.0-helm-chart.tgz \
  -n opendmt3 --create-namespace \
  --set admin.enabled=true --set admin.password=CHANGE1234
```

From a copy of the repository, the chart is `deploy/helm/opendmt3`. Each chart runs the server of its own version
(`image.tag` empty), from `ghcr.io/kanggu12/opendmt3-server`, built for amd64 and arm64.

## The first account

On a cluster no visit to the site comes from the server's own PC, so the site's first-run page never shows. With
`admin.enabled=true` the chart makes the first account, with the admin pages, before the server starts, but only
while the database has no account at all. Later changes to these values change nothing.

- `admin.id`: the account's ID (`BOSS` by default).
- `admin.password`: its password, 6 to 16 letters and digits. The chart keeps it in a Secret of its own.
- `admin.existingSecret`: a Secret of yours with the key `password`, in place of `admin.password`, so the release's
  values never hold it:

```sh
kubectl -n opendmt3 create secret generic dmt3-admin --from-literal=password=CHANGE1234
helm install dmt3 ... --set admin.enabled=true --set admin.existingSecret=dmt3-admin
```

Without the chart, make it in the running pod (the password is printed):

```sh
kubectl -n opendmt3 exec deploy/dmt3-opendmt3 -- python -m opendmt3.server --data /data --add-player BOSS --admin
```

## The song list

The server needs only the song list from your client data ([The song list](server.md#the-song-list)). Save it with
the launcher (**Game**, **Save the song list...**) or with `./dmt3 catalog PATH --save FILE`, then do one of these:

- On the admin pages: **Song list**, upload the file.
- With the API: `POST /api/v1/server/song_list` with the file as the body ([api.md](api.md)).
- Copy it into the pod and import it there:

```sh
POD=$(kubectl -n opendmt3 get pod -l app.kubernetes.io/instance=dmt3 -o name | head -1)
kubectl -n opendmt3 cp opendmt3-song-list.zip "${POD#pod/}":/data/opendmt3-song-list.zip -c server
kubectl -n opendmt3 exec deploy/dmt3-opendmt3 -c server -- \
  python -m opendmt3.server --data /data --catalog /data/opendmt3-song-list.zip --setup-only
```

The site shows the new song list at once. To hand out the launcher, copy the release's installer into the
downloads folder the same way:

```sh
kubectl -n opendmt3 cp opendmt3-launcher-0.4.0-windows-x64-setup.exe "${POD#pod/}":/data/downloads/openDMT3-win-Setup.exe -c server
```

## The game's port

Cabinets connect to TCP 4725 at the game Service's outside address. On a cloud, the default `LoadBalancer` gets one:

```sh
kubectl -n opendmt3 get svc dmt3-opendmt3-game
```

- `game.service.loadBalancerIP` keeps a fixed address, where the cloud allows it, and
  `game.service.annotations` takes the cloud's own settings (an internal load balancer, say).
- On a cluster without load balancers, `game.service.type=NodePort` and `game.service.nodePort=30725`: cabinets
  connect to any node's address on that port.
- Another port: `game.service.port=5725`. The server listens on the port cabinets reach (the node's port with
  `NodePort`, else the Service's), so the site tells launchers that one.

Cabinets behind one router share its address: the game's port takes up to 16 of them from one address, and 64 in all.

## HTTPS with an Ingress

Sign-ins carry passwords, so the site goes on the internet over HTTPS. With an Ingress controller and
[cert-manager](https://cert-manager.io) in the cluster:

```yaml
siteAddress: https://dmt.example.org/
# The Ingress controller's pods: their forwarded headers are believed, from there only.
proxy: 10.244.0.0/16
ingress:
  enabled: true
  className: nginx
  host: dmt.example.org
  annotations:
    cert-manager.io/cluster-issuer: letsencrypt
    # An uploaded song list or backup is larger than nginx takes by default.
    nginx.ingress.kubernetes.io/proxy-body-size: 300m
  tls:
    - secretName: dmt3-tls
      hosts: [dmt.example.org]
```

```sh
helm upgrade --install dmt3 ... -n opendmt3 -f my-values.yaml
```

- `siteAddress` is the address players reach the site at: the message the admin pages make for a new player
  carries it.
- `proxy` names the addresses the controller's connections come from: a pod network such as `10.244.0.0/16`, or
  several with commas. The site then tells visitors apart (a wrong password holds back only its own address) and
  HTTPS sign-ins get secure cookies. Your cluster's pod network is in `kubectl cluster-info dump | grep -m1 cluster-cidr`.
- cert-manager makes the certificate in `dmt3-tls` and renews it. A Secret you made yourself works the same way,
  without the annotation.

The launchers then use `https://dmt.example.org/` as the server's address, and the game's port stays as it is.

## Values

The chart's [values.yaml](https://github.com/kanggu12/openDMT3/blob/main/deploy/helm/opendmt3/values.yaml) says what each one does. The ones most owners set:

- `siteAddress`, `proxy`, `webhook` (a Discord or Slack webhook for new first places), `extraArgs` (more of the
  server's own options).
- `admin.*`, above.
- `game.service.*`, `site.service.*`, `ingress.*`, above.
- `persistence.size` (2 GiB by default), `persistence.storageClass`, `persistence.existingClaim` (a volume of yours),
  `persistence.enabled=false` (data that lasts as long as the pod, for a test).
- `image.repository` and `image.tag`, for a copy in a registry of your own.
- `resources`, `nodeSelector`, `tolerations`, `affinity`, `podAnnotations`, `podLabels`.

## Backups

The server backs its database up once a day onto its volume and keeps a week of them. The admin pages' **Backups**
makes, downloads and restores them. From the command line:

```sh
kubectl -n opendmt3 exec deploy/dmt3-opendmt3 -c server -- python -m opendmt3.server --data /data --backup
kubectl -n opendmt3 exec deploy/dmt3-opendmt3 -c server -- python -m opendmt3.server --data /data --backups
```

To keep one off the cluster, download it from the admin pages or copy it out:

```sh
kubectl -n opendmt3 cp "${POD#pod/}":/data/backups/NAME.sqlite NAME.sqlite -c server
```

## Updating

Install the new release's chart over the old one:

```sh
helm upgrade dmt3 https://github.com/kanggu12/openDMT3/releases/download/v0.4.0/opendmt3-server-0.4.0-helm-chart.tgz \
  -n opendmt3 --reuse-values
```

The old pod stops, the new one starts on the same volume, and a newer server takes the database forward on its first
start (a copy of it is kept first). Then copy the new launcher's installer into `/data/downloads/` as above.

`helm uninstall dmt3 -n opendmt3` removes the server and keeps the volume. `kubectl -n opendmt3 delete pvc
dmt3-opendmt3-data` removes the data too.

## The admin pages

The admin pages are a site of their own, on port 4731, with a Service of their own inside the cluster
(`dmt3-opendmt3-admin`, ClusterIP: never a LoadBalancer or a NodePort, whatever the site's Service is). From your PC:

```sh
kubectl -n opendmt3 port-forward svc/dmt3-opendmt3-admin 4731:4731
```

then open `http://127.0.0.1:4731/` and sign in with an account that has admin rights (the chart's notes print the
same line). The site's port answers none of them.

`admin.onPublicPort: true` serves them on the site's port too, at `/admin/` (the server's `--admin-on-site-port`), so
the site's Ingress puts them at `https://dmt.example.org/admin/`: one address for both, over HTTPS. Their sign-in is
then on the internet; without it, nothing of them leaves the cluster. `admin.service.port` sets the admin Service's
port.

## The admin's Server tab

The cluster starts the server and keeps it running, so the tab asks it nothing: it has no Restart, Stop or Remove
buttons here, and names the cluster's commands instead, with this release's names (the chart tells the server its
namespace, release, Deployment and claim):

- start and stop: `kubectl -n opendmt3 scale deployment/dmt3-opendmt3 --replicas=1` (and `--replicas=0`);
- restart: `kubectl -n opendmt3 rollout restart deployment/dmt3-opendmt3`, a new pod on the same volume;
- remove: `helm -n opendmt3 uninstall dmt3`, and with the data
  `helm -n opendmt3 uninstall dmt3 && kubectl -n opendmt3 delete pvc dmt3-opendmt3-data`.

`GET /api/v1/server` gives the same as `runner` (`kind` `kubernetes`), and `POST /api/v1/server/stop`, `restart` and
`remove` answer `409 not_here` with the command.

## Trying it on kind

`deploy/kind/up.sh` runs the chart on a local [kind](https://kind.sigs.k8s.io) cluster named `odt3-srv-kind`, with
Docker, kind, kubectl and Helm on the PC. It builds the image from the tree, starts the cluster, installs the chart
with [deploy/kind/values.yaml](https://github.com/kanggu12/openDMT3/blob/main/deploy/kind/values.yaml), and checks from the PC:

- `/health` and the sign-in page on `http://127.0.0.1:14730/`;
- the game's port on `127.0.0.1:14725`;
- the first account from the chart's Secret signing in through the API, with the admin pages;
- the Server tab's runner, the cluster's commands with the release's names;
- the admin pages through `kubectl port-forward`, and none of them on the site's port;
- after a restart, the same account, with none made again;
- `helm test`, which asks `/health` from inside the cluster.

Each check prints `PASS` or `FAIL`. The cluster stays up afterwards; `deploy/kind/up.sh --down` deletes it at the end,
and `kind delete cluster --name odt3-srv-kind` does it later.
