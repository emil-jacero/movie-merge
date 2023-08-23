# movie-merge

## Build

```shell
docker buildx build --load \
--platform linux/amd64 \
--tag emil-jacero/movie-merge:dev .
```

## Run

```shell
docker run --rm -it -v /path/to/video-files/directory:/folder emil-jacero/movie-mer
ge:dev -i /folder -o /folder
```
