import React from "react";
import Spinner from "react-bootstrap/Spinner";

export default function Loader() {
  return (
    <div className="text-center py-4">
      <Spinner animation="border" role="status">
        <span className="visually-hidden">Loading...</span>
      </Spinner>
    </div>
  );
}
