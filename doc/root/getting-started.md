# 快速开始

- 准备一个 `demo.yml`：
  ```yaml
  name: "demo"
  inet: "10.66.66.0/24"
  images:
  - name: "bind"
      ref: "bind:9.18.0"
  builds:
  - recursor:
      image: "bind"
      ref: "std:recursor"
      behavior: . hint root
  - root:
      image: "bind"
      ref: "std:auth"
      behavior: |
          . master com NS tld
  - tld:
      image: "bind"
      ref: "std:auth"
      behavior: |
          com master example NS sld
  - sld:
      image: "bind"
      ref: "std:auth"
      behavior: |
          example.com master www A 1.2.3.4
          example.com master mail A 1.2.3.5
  ```
  该配置文件用于生成一个简单的 `root -> tld -> sld`DNS服务环境，模拟现实世界中查询 `*.example.com`的过程


- 运行
  ```shell
  dnsb demo.yml [--debug]
  ```
  在运行目录下的 `output/demo`可以看到完整的 `docker-compose`项目，运行 `docker compose up --build`即可构建完整环境
