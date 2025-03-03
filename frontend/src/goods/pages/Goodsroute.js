import React, { useState, useEffect } from "react";
import { Route, Routes, useSearchParams } from "react-router-dom";
import Goods from "./Goods";
import Goodsview from "./Goodsview";
import { useHttpClient } from "../components/Goods-http-hook"; //api호출 훅 불러오기

const Goodsroute = () => {
  const [searchParams, setSearchParams] = useSearchParams();
  const searchparamshandler = (sort, value) => {
    //쿼리 생성 및 변경
    searchParams.set(`${sort}`, `${value}`);
    setSearchParams(searchParams);
  };

  const { isLoading, error, sendRequest } = useHttpClient();
  const [loadedGoods, setLoadedGoods] = useState([]);
  const [totalcount, setTotalcount] = useState(100);

  const currentPath = window.location.pathname;
  useEffect(() => {
    const fetchgoods = async (event) => {
      try {
        const { responseData, total_count } = await sendRequest(
          `${process.env.REACT_APP_BACKEND_URL}/purchase/goods/${
            searchParams.get("price") ? searchParams.get("price") : "asc"
          }?${
            searchParams.get("page") ? `page=${searchParams.get("page")}` : ""
          }${
            searchParams.get("rating") && searchParams.get("rating") != ""
              ? `&rating=${searchParams.get("rating")}`
              : ""
          }`
        );

        setTotalcount(total_count);
        setLoadedGoods(responseData);
      } catch (err) {
        alert("정보를 수정할 수 없습니다.");
      }
    };

    fetchgoods();
  }, [searchParams]);

  return (
    <React.Fragment>
      <Routes>
        <Route
          path="/"
          exact
          element={
            <Goods
              isLoading={isLoading}
              loadedGoods={loadedGoods}
              searchParams={searchParams}
              setSearchParams={setSearchParams}
              searchparamshandler={searchparamshandler}
              totalcount={totalcount}
              error={error}
            />
          }
        />

        <Route
          path="/detail/:goodsNo"
          exact
          element={
            <Goodsview
              isLoading={isLoading}
              loadedGoods={loadedGoods}
              searchParams={searchParams}
            />
          }
        />
      </Routes>
    </React.Fragment>
  );
};

export default Goodsroute;
